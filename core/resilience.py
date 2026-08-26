"""Circuit breaker + token-bucket rate limiter for outbound LLM providers.

Block A.1 (breaker) and A.6 (preventive client-side throttling).

The state is kept per-process (one asyncio loop). For multi-worker deployments
either enable sticky provider routing or move breaker counters to Redis — see
ARCHITECTURE.md, "Распределённый деплой".
"""

import asyncio
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


@dataclass
class BreakerConfig:
    failure_threshold: int = 5          # consecutive failures before opening
    recovery_base_seconds: float = 10.0  # first recovery window
    recovery_max_seconds: float = 600.0  # cap for exponential growth


class CircuitBreaker:
    """Async circuit breaker with exponential recovery window and half-open probing."""

    def __init__(self, name: str, config: Optional[BreakerConfig] = None):
        self.name = name
        self.config = config or BreakerConfig()
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._open_count = 0
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        # Lazily transition OPEN -> HALF_OPEN when the recovery window elapsed;
        # the actual probe admission happens in acquire().
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def _recovery_window(self) -> float:
        """Exponentially growing recovery window with jitter."""
        exponent = max(self._open_count - 1, 0)
        window = self.config.recovery_base_seconds * (2 ** exponent)
        window = min(window, self.config.recovery_max_seconds)
        jitter = random.uniform(0, window * 0.1)
        return window + jitter

    async def acquire(self) -> None:
        """Admit a call or raise CircuitOpenError."""
        now = time.monotonic()
        if self._state == BreakerState.OPEN:
            if now - self._opened_at >= self._recovery_window():
                self._state = BreakerState.HALF_OPEN
                self._probe_in_flight = False
            else:
                raise CircuitOpenError(
                    f"provider '{self.name}' circuit is open "
                    f"(retry allowed in {self._recovery_window() - (now - self._opened_at):.1f}s)"
                )
        if self._state == BreakerState.HALF_OPEN:
            if self._probe_in_flight:
                raise CircuitOpenError(
                    f"provider '{self.name}' probe already in flight"
                )
            self._probe_in_flight = True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._probe_in_flight = False
        self._state = BreakerState.CLOSED

    def record_failure(self) -> None:
        self._probe_in_flight = False
        self._consecutive_failures += 1
        should_open = (
            self._state == BreakerState.HALF_OPEN
            or self._consecutive_failures >= self.config.failure_threshold
        )
        if should_open:
            self._state = BreakerState.OPEN
            self._opened_at = time.monotonic()
            self._open_count += 1
            self._consecutive_failures = 0


class TokenBucketRateLimiter:
    """Preventive client-side throttling calibrated to provider API quotas.

    Instead of discovering 429 post-factum, outgoing calls consume a token;
    when the bucket is empty callers asynchronously wait (bounded by timeout).
    """

    def __init__(
        self,
        name: str,
        capacity: int = 30,
        refill_rate_per_sec: float = 0.5,
    ):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if refill_rate_per_sec <= 0:
            raise ValueError("refill_rate_per_sec must be positive")
        self.name = name
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate_per_sec)
        self._tokens = float(capacity)
        self._updated_at = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(
            self.capacity,
            self._tokens + (now - self._updated_at) * self.refill_rate,
        )
        self._updated_at = now

    @property
    def available_tokens(self) -> float:
        self._refill()
        return self._tokens

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """Take one token. Returns False if timeout elapsed without availability."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            wait = (1.0 - self._tokens) / self.refill_rate
            if deadline is not None and time.monotonic() + min(wait, 0.5) > deadline:
                return False
            await asyncio.sleep(min(wait, 0.5))
