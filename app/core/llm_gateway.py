"""Resilient gateway in front of vision-LLM providers.

Combines Block A.1 / A.3 / A.4 / A.6:

- token-bucket throttling per provider (never discover 429 post-factum),
- circuit breaker per provider with automatic failover to the next configured
  provider (logged on every switch),
- strict Pydantic validation of every response, with exactly ONE corrective
  retry that shows the model its previous invalid output,
- graceful degradation: if every provider is unreachable -> AllProvidersDownError
  (caller enqueues a retry); if models answer but output garbage everywhere ->
  manual-review verdict instead of HTTP 500,
- usage tracking (tokens) for cost-per-check metrics.
"""

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.core.config import get_api_key_for_provider, get_llm_provider, settings
from app.core.deadline import current_deadline
from app.core.metrics import BREAKER_STATE, LLM_REQUESTS, LLM_TOKENS_TOTAL
from app.core.resilience import (
    BreakerConfig,
    CircuitBreaker,
    CircuitOpenError,
    TokenBucketRateLimiter,
)
from app.llm_provider import PROMPT_VERSION, build_analysis_prompt, ProviderType, VisionProvider
from app.models.schemas import AnalysisResult

logger = logging.getLogger(__name__)

# Transient errors worth an immediate in-place retry (network layer only).
_TRANSIENT_EXCEPTIONS: tuple = (ConnectionError, TimeoutError)

_TRANSIENT_RETRIES = 2          # quick network-level retries inside one attempt
_RATE_LIMIT_ACQUIRE_TIMEOUT = 5.0


class InvalidModelOutputError(RuntimeError):
    """Model answered twice with structurally invalid JSON."""


class AllProvidersUnavailableError(RuntimeError):
    """Base: no provider produced a usable verdict."""

    def __init__(self, message: str, attempts: List[Dict[str, Any]]):
        super().__init__(message)
        self.attempts = attempts


class AllProvidersDownError(AllProvidersUnavailableError):
    """Every provider was unreachable / circuit-open / timed out -> queueable."""


class AllOutputsInvalidError(AllProvidersUnavailableError):
    """Models reachable but every answer failed validation -> graceful fallback."""


# --- Per-process resilience state ------------------------------------------------

_breakers: Dict[str, CircuitBreaker] = {}
_buckets: Dict[str, TokenBucketRateLimiter] = {}


def _breaker_config() -> BreakerConfig:
    return BreakerConfig(
        failure_threshold=settings.cb_failure_threshold,
        recovery_base_seconds=settings.cb_recovery_base_seconds,
        recovery_max_seconds=settings.cb_recovery_max_seconds,
    )


def get_breaker(provider_name: str) -> CircuitBreaker:
    if provider_name not in _breakers:
        _breakers[provider_name] = CircuitBreaker(provider_name, _breaker_config())
    return _breakers[provider_name]


def get_bucket(provider_name: str) -> TokenBucketRateLimiter:
    if provider_name not in _buckets:
        _buckets[provider_name] = TokenBucketRateLimiter(
            provider_name,
            capacity=settings.rl_capacity,
            refill_rate_per_sec=settings.rl_refill_rate,
        )
    return _buckets[provider_name]


def reset_resilience_state() -> None:
    """Used by tests."""
    _breakers.clear()
    _buckets.clear()


def configured_providers(preferred: Optional[str] = None) -> List[str]:
    """Providers ordered by preference, filtered to those having API keys.

    ``mock`` (A-C4, load-test-only provider) is never added as an automatic
    failover/consensus candidate — it only appears here when explicitly
    requested as ``preferred`` (i.e. PROVIDER=mock).
    """
    explicit = (preferred or settings.provider).strip().lower()
    order = [explicit] + [
        p.value for p in ProviderType if p != ProviderType.MOCK
    ]
    seen: List[str] = []
    for name in order:
        if name in seen:
            continue
        try:
            ProviderType(name)
        except ValueError:
            continue
        if get_api_key_for_provider(name):
            seen.append(name)
    return seen


def prompt_fingerprint(meta: Dict[str, Any]) -> Dict[str, str]:
    """Prompt version + hash stored alongside every verdict (Block A.8)."""
    text = build_analysis_prompt(meta)
    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": hashlib.sha256(text.encode()).hexdigest(),
    }


def _sync_breaker_gauge(name: str) -> None:
    state = get_breaker(name).state.value
    BREAKER_STATE.labels(provider=name).set({"closed": 0, "half_open": 1, "open": 2}[state])


async def _call_with_transient_retry(
    provider: VisionProvider,
    original_bytes: bytes,
    suspect_bytes: bytes,
    meta: Dict[str, Any],
    timeout: Optional[float],
    provider_label: str,
):
    """Network-level quick retry for transient failures inside one attempt."""
    last_exc: Optional[Exception] = None
    for attempt in range(_TRANSIENT_RETRIES + 1):
        call = provider.analyze(original_bytes, suspect_bytes, meta)
        try:
            if timeout is not None:
                return await asyncio.wait_for(call, timeout=max(timeout, 0.1))
            return await call
        except _TRANSIENT_EXCEPTIONS as e:
            last_exc = e
            if attempt < _TRANSIENT_RETRIES:
                logger.warning(f"[{provider_label}] transient error ({e}), retrying")
                await asyncio.sleep(0.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


async def validated_provider_call(
    provider: VisionProvider,
    original_bytes: bytes,
    suspect_bytes: bytes,
    meta: Dict[str, Any],
    provider_label: str = "provider",
) -> AnalysisResult:
    """Call one provider and strictly validate the answer; ONE corrective retry.

    Raises InvalidModelOutputError if validation fails twice. Used directly by
    the aggregator/batch paths that pin a specific provider instance.
    """
    raw = await provider.analyze(original_bytes, suspect_bytes, meta)
    try:
        return _validate_and_track(raw, provider_label)
    except ValidationError as first_error:
        logger.warning(f"[{provider_label}] invalid LLM output, sending corrective retry")
        correction = dict(meta)
        correction["_correction"] = {
            "previous_output": str(raw)[:1500],
            "problem": f"Ответ не соответствует схеме: {first_error.errors()[:3]}",
            "instruction": (
                "Твой предыдущий ответ невалиден. Верни СТРОГО валидный JSON без "
                "markdown со всеми обязательными полями."
            ),
        }
        retry_raw = await provider.analyze(original_bytes, suspect_bytes, correction)
        try:
            result = _validate_and_track(retry_raw, provider_label)
            logger.info(f"[{provider_label}] corrective retry succeeded")
            return result
        except ValidationError as second_error:
            raise InvalidModelOutputError(str(second_error)) from second_error


def _validate_and_track(raw: Any, provider_label: str) -> AnalysisResult:
    """Strict validation + token-usage extraction (Block A.4 / A.5)."""
    result = AnalysisResult.model_validate(raw)
    usage = raw.get("_usage") if isinstance(raw, dict) else None
    if isinstance(usage, dict) and usage.get("total_tokens"):
        result._usage_tokens = int(usage["total_tokens"])  # noqa: SLF001
    return result


async def analyze_resilient(
    original_bytes: bytes,
    suspect_bytes: bytes,
    meta: Dict[str, Any],
    preferred_provider: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full resilient analysis path with failover.

    Returns (result_dict, source_meta). Raises AllProvidersDownError (queueable)
    or AllOutputsInvalidError (graceful manual-review fallback).
    """
    providers = configured_providers(preferred_provider)
    if not providers:
        raise AllProvidersDownError("No LLM provider has a configured API key", [])

    deadline = current_deadline()
    attempts: List[Dict[str, Any]] = []
    had_invalid_output = False

    for name in providers:
        bucket = get_bucket(name)
        breaker = get_breaker(name)

        # 1) Preventive rate limiting.
        acquire_timeout = _RATE_LIMIT_ACQUIRE_TIMEOUT
        if deadline is not None:
            acquire_timeout = min(acquire_timeout, deadline.remaining())
        if not await bucket.acquire(timeout=acquire_timeout):
            LLM_REQUESTS.labels(provider=name, outcome="rate_limited").inc()
            attempts.append({"provider": name, "outcome": "rate_limited"})
            continue

        # 2) Circuit breaker admission.
        try:
            await breaker.acquire()
        except CircuitOpenError as e:
            logger.warning(f"Failover: {e}")
            LLM_REQUESTS.labels(provider=name, outcome="circuit_open").inc()
            attempts.append({"provider": name, "outcome": "circuit_open"})
            _sync_breaker_gauge(name)
            continue

        # 3) The actual call + strict validation.
        call_timeout = deadline.remaining() if deadline is not None else None
        try:
            result = await _single_attempt(name, original_bytes, suspect_bytes, meta, call_timeout)
        except InvalidModelOutputError as e:
            breaker.record_failure()
            _sync_breaker_gauge(name)
            had_invalid_output = True
            LLM_REQUESTS.labels(provider=name, outcome="invalid_json").inc()
            attempts.append({"provider": name, "outcome": "invalid_json", "error": str(e)[:200]})
            logger.error(f"[{name}] invalid model output after corrective retry")
            continue
        except asyncio.TimeoutError:
            breaker.record_failure()
            _sync_breaker_gauge(name)
            LLM_REQUESTS.labels(provider=name, outcome="timeout").inc()
            attempts.append({"provider": name, "outcome": "timeout"})
            if deadline is not None and deadline.expired():
                break  # budget exhausted — no point trying other providers
            continue
        except Exception as e:  # noqa: BLE001
            breaker.record_failure()
            _sync_breaker_gauge(name)
            LLM_REQUESTS.labels(provider=name, outcome="transient_error").inc()
            attempts.append({"provider": name, "outcome": "error", "error": str(e)[:200]})
            logger.error(f"[{name}] provider error, failing over: {e}")
            continue

        breaker.record_success()
        _sync_breaker_gauge(name)
        LLM_REQUESTS.labels(provider=name, outcome="success").inc()

        data = result.model_dump()
        usage_tokens = getattr(result, "_usage_tokens", None)
        if usage_tokens:
            LLM_TOKENS_TOTAL.labels(provider=name).inc(usage_tokens)
            data["tokens_used"] = usage_tokens

        source = {
            "provider": name,
            "verdict_source": "llm_analysis",
            **prompt_fingerprint(meta),
        }
        return data, source

    if had_invalid_output:
        raise AllOutputsInvalidError("All providers returned invalid output", attempts)
    raise AllProvidersDownError("All configured providers are unavailable", attempts)


# --- Multi-model consensus (Block B.3) --------------------------------------------

MANUAL_REVIEW = "ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ"


async def run_consensus(
    first_result: Dict[str, Any],
    first_provider: Optional[str],
    original_bytes: bytes,
    suspect_bytes: bytes,
    meta: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Second-opinion pass for borderline cases.

    Trigger: first-pass confidence inside the configured band
    [consensus_confidence_low .. consensus_confidence_high].

    Rules (explicit and documented in README):
    - both providers give the SAME verdict  → confidence boosted to their average +10;
    - verdicts DIVERGE                      → verdict becomes "manual review", both raw
                                              answers are preserved for audit;
    - second provider unavailable/fails     → first verdict kept, consensus marked
                                              "second_opinion_unavailable".

    Returns (possibly modified result, consensus_meta).
    """
    low = settings.consensus_confidence_low
    high = settings.consensus_confidence_high
    confidence = int(first_result.get("confidence") or 0)
    consensus_meta = {"consensus": "not_needed"}

    try:
        if not (low <= confidence <= high):
            return first_result, consensus_meta

        others = [
            p for p in configured_providers()
            if p != (first_provider or "").strip().lower()
        ]
        if not others:
            consensus_meta["consensus"] = "second_opinion_unavailable"
            return first_result, consensus_meta

        deadline = current_deadline()
        call_timeout = deadline.remaining() if deadline is not None else None
        name = others[0]

        async def _second():
            return await _single_attempt(
                name, original_bytes, suspect_bytes, meta, call_timeout
            )

        # Parallel-safe structure (single extra provider today; asyncio.gather
        # scales to N models for an ensemble without changing aggregation).
        results = await asyncio.gather(_second(), return_exceptions=True)

        raw_responses = [{
            "provider": first_provider,
            "verdict": first_result.get("verdict"),
            "confidence": confidence,
            "summary": first_result.get("summary", ""),
        }]

        second = results[0]
        if isinstance(second, Exception):
            logger.warning(f"[{name}] consensus second opinion failed: {second}")
            consensus_meta["consensus"] = "second_opinion_unavailable"
            first_result["raw_model_responses"] = raw_responses
            return first_result, consensus_meta

        second_dict = second.model_dump()
        raw_responses.append({
            "provider": name,
            "verdict": second_dict.get("verdict"),
            "confidence": second_dict.get("confidence"),
            "summary": second_dict.get("summary", ""),
        })

        first_result["raw_model_responses"] = raw_responses

        if second_dict.get("verdict") == first_result.get("verdict"):
            avg = (confidence + int(second_dict.get("confidence") or 0)) // 2
            first_result["confidence"] = min(99, avg + 10)
            consensus_meta["consensus"] = "agreement"
            logger.info(
                f"Consensus AGREEMENT on '{first_result.get('verdict')}' "
                f"(both {first_provider} and {name})"
            )
        else:
            first_result["verdict"] = MANUAL_REVIEW
            first_result["risk_level"] = "unknown"
            first_result["summary"] = (
                f"Модели разошлись во мнении ({first_provider}: "
                f"{raw_responses[0]['verdict']}, {name}: {second_dict['verdict']}); "
                f"требуется ручная проверка эксперта"
            )
            first_result["confidence"] = (
                confidence + int(second_dict.get("confidence") or 0)
            ) // 2
            consensus_meta["consensus"] = "disagreement"
            logger.info(
                f"Consensus DISAGREEMENT ({first_provider}: "
                f"{raw_responses[0]['verdict']} vs {name}: {second_dict['verdict']}) "
                f"— escalated to manual review"
            )

        consensus_meta["consensus_provider"] = name
        return first_result, consensus_meta
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - consensus must never break analysis
        logger.error(f"Consensus step error: {e}")
        consensus_meta["consensus"] = "error"
        return first_result, consensus_meta


async def _single_attempt(
    name: str,
    original_bytes: bytes,
    suspect_bytes: bytes,
    meta: Dict[str, Any],
    call_timeout: Optional[float],
) -> AnalysisResult:
    """One provider attempt: transient-retried call + strict validation."""
    provider = get_llm_provider(name)
    raw = await _call_with_transient_retry(
        provider, original_bytes, suspect_bytes, meta, call_timeout, name
    )
    try:
        return _validate_and_track(raw, name)
    except ValidationError:
        # Exactly one corrective retry showing the model its bad output.
        correction = dict(meta)
        correction["_correction"] = {"previous_output": str(raw)[:1500]}
        retry_raw = await _call_with_transient_retry(
            provider, original_bytes, suspect_bytes, correction, call_timeout, name
        )
        try:
            result = _validate_and_track(retry_raw, name)
            logger.info(f"[{name}] corrective retry succeeded")
            return result
        except ValidationError as second_error:
            raise InvalidModelOutputError(str(second_error)) from second_error


