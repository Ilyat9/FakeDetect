"""Block A unit tests: circuit breaker, token bucket, deadline."""

import asyncio

import pytest

from core.deadline import Deadline, DeadlineExceeded, current_deadline, set_deadline
from core.resilience import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
    TokenBucketRateLimiter,
)


@pytest.mark.asyncio
async def test_breaker_opens_after_threshold():
    breaker = CircuitBreaker("test", BreakerConfig(failure_threshold=3))
    for _ in range(2):
        await breaker.acquire()
        breaker.record_failure()
    # Still closed below threshold.
    await breaker.acquire()
    breaker.record_failure()  # 3rd -> open
    with pytest.raises(CircuitOpenError):
        await breaker.acquire()
    assert breaker.state == BreakerState.OPEN


@pytest.mark.asyncio
async def test_breaker_half_open_probe_admission():
    breaker = CircuitBreaker("test", BreakerConfig(
        failure_threshold=1, recovery_base_seconds=0.0,
    ))
    await breaker.acquire()
    breaker.record_failure()
    assert breaker.state == BreakerState.OPEN
    await asyncio.sleep(0.01)  # recovery window elapsed
    await breaker.acquire()   # admitted as probe -> half-open
    assert breaker.state == BreakerState.HALF_OPEN
    with pytest.raises(CircuitOpenError):
        await breaker.acquire()  # second concurrent call rejected while probing
    breaker.record_success()
    assert breaker.state == BreakerState.CLOSED


@pytest.mark.asyncio
async def test_breaker_recovery_window_grows_exponentially():
    breaker = CircuitBreaker("test", BreakerConfig(
        failure_threshold=1, recovery_base_seconds=10, recovery_max_seconds=1000,
    ))
    windows = []
    for _ in range(4):
        await breaker.acquire()
        breaker.record_failure()
        windows.append(breaker._recovery_window())
        breaker._opened_at -= 9999  # force window elapsed for next cycle
    assert windows[1] > windows[0]
    assert windows[3] <= 1000 * 1.1  # capped


@pytest.mark.asyncio
async def test_token_bucket_throttles():
    bucket = TokenBucketRateLimiter("t", capacity=2, refill_rate_per_sec=50)
    assert await bucket.acquire(timeout=1) is True
    assert await bucket.acquire(timeout=1) is True
    # Bucket empty; refill at 50/s means next token in ~20ms.
    assert await bucket.acquire(timeout=1) is True
    start = asyncio.get_event_loop().time()
    drained = TokenBucketRateLimiter("t2", capacity=1, refill_rate_per_sec=1)
    assert await drained.acquire(timeout=0) is True
    assert await drained.acquire(timeout=0.05) is False  # no tokens within timeout


def test_deadline_budget_and_contextvar():
    deadline = Deadline(0.5)
    assert deadline.remaining() > 0.4
    token = set_deadline(deadline)
    try:
        assert current_deadline() is deadline
        with pytest.raises(ValueError):
            Deadline(0)
    finally:
        from core.deadline import reset_deadline
        reset_deadline(token)
