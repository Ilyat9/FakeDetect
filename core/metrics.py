"""Prometheus metrics (Block A.5).

Own CollectorRegistry to avoid double-registration on app reloads in tests.
Exposed via GET /metrics.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

# --- HTTP layer ----------------------------------------------------------------
REQUEST_LATENCY = Histogram(
    "fakedetect_request_latency_seconds",
    "Endpoint latency (p50/p95/p99 from buckets)",
    ["endpoint", "method"],
    registry=REGISTRY,
)
HTTP_ERRORS_TOTAL = Counter(
    "fakedetect_http_errors_total",
    "HTTP 5xx responses",
    ["endpoint", "method"],
    registry=REGISTRY,
)

# --- LLM provider layer (error rate tracked separately from the app) ----------
LLM_REQUESTS = Counter(
    "fakedetect_llm_requests_total",
    "LLM call outcomes per provider",
    ["provider", "outcome"],  # outcome: success|invalid_json|transient_error|circuit_open|rate_limited|timeout
    registry=REGISTRY,
)
LLM_TOKENS_TOTAL = Counter(
    "fakedetect_llm_tokens_total",
    "Tokens consumed per provider (cost-per-check tracking)",
    ["provider"],
    registry=REGISTRY,
)
BREAKER_STATE = Gauge(
    "fakedetect_provider_breaker_state",
    "0=closed 1=half_open 2=open",
    ["provider"],
    registry=REGISTRY,
)

# --- Infrastructure -------------------------------------------------------------
PLAYWRIGHT_SESSIONS = Gauge(
    "fakedetect_playwright_active_sessions",
    "Currently open headless browser sessions",
    registry=REGISTRY,
)
BATCH_QUEUE_SIZE = Gauge(
    "fakedetect_batch_queue_size",
    "Batch tasks currently in 'processing' state",
    registry=REGISTRY,
)
RETRY_QUEUE_SIZE = Gauge(
    "fakedetect_retry_queue_size",
    "Analyses waiting in the retry queue (all providers were down)",
    registry=REGISTRY,
)


def render_metrics() -> tuple[bytes, str]:
    """Return (payload, content_type) for the /metrics endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
