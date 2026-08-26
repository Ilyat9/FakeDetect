"""Application configuration and LLM provider management."""

import logging
from typing import Dict, Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm_provider import ProviderType, VisionProvider, create_provider

logger = logging.getLogger(__name__)

# --- Limits -------------------------------------------------------------------

MAX_IMAGE_UPLOAD_BYTES = 15 * 1024 * 1024   # 15 MB per image
MAX_EXCEL_UPLOAD_BYTES = 25 * 1024 * 1024   # 25 MB per Excel file
DEEP_ANALYSIS_TIMEOUT_SECONDS = 60


class Settings(BaseSettings):
    provider: str = "gemini"
    gemini_api_key: Optional[SecretStr] = None
    grok_api_key: Optional[SecretStr] = None
    telegram_bot_token: Optional[SecretStr] = None
    telegram_chat_id: Optional[str] = None
    # Comma-separated list of allowed CORS origins; empty = same-origin only.
    allowed_origins: str = ""
    # If set, protected endpoints require the X-API-Key header.
    api_secret_key: Optional[SecretStr] = None

    # --- Block A: production reliability --------------------------------------
    # A.5: structured JSON logs when set to "json".
    log_format: str = "text"
    # A.3: single timeout budget for the whole request path (seconds).
    request_timeout_budget_seconds: float = 55.0
    # A.1: circuit breaker per provider.
    cb_failure_threshold: int = 5            # consecutive failures -> open
    cb_recovery_base_seconds: float = 10.0   # first recovery window (exponential growth)
    cb_recovery_max_seconds: float = 600.0
    # A.6: preventive token-bucket throttling per provider (calibrated to quota).
    rl_capacity: int = 30                    # burst capacity (tokens)
    rl_refill_rate: float = 0.5              # sustained rate (tokens per second)
    # A.6: queueing instead of 500 when every provider is down.
    retry_queue_poll_seconds: float = 15.0
    retry_queue_max_attempts: int = 5
    # A.2: idempotency cache TTL for stored verdicts.
    idempotency_ttl_hours: int = 24

    # --- Block B: forensic layers ----------------------------------------------
    # B.1: hamming distance threshold for "same image" (8x8 pHash has 64 bits).
    phash_hamming_threshold: int = 8
    # B.2: ELA calibration.
    ela_quality: int = 90
    ela_flag_threshold: float = 25.0
    # B.3: multi-model consensus band — first-pass confidence inside [low..high]
    # triggers a second provider opinion.
    consensus_confidence_low: int = 40
    consensus_confidence_high: int = 70
    # B.4: composite score weights (Σ w·s / Σw over available signals).
    w_llm_confidence: float = 0.45
    w_phash_similarity: float = 0.25
    w_ela: float = 0.15
    w_exif: float = 0.05
    w_price: float = 0.10
    # price authenticity mapping: ratio<=floor → 0, >=ceiling → 100.
    price_floor: float = 0.2
    price_ceiling: float = 0.8

    # --- Block C: discovery / autonomous monitoring -----------------------------
    discovery_tick_seconds: float = 60.0      # scheduler poll interval
    scheduler_due_batch: int = 5              # watches started per tick
    discovery_max_listings_per_keyword: int = 20
    discovery_concurrency: int = 3            # parallel listing analyses
    recheck_original_days: int = 7            # TTL by verdict (C.3)
    recheck_suspicious_days: int = 2
    recheck_fake_days: int = 1
    digest_default_hours: int = 24

    # --- Block D: evidence & workflow -------------------------------------------
    evidence_screenshots_enabled: bool = True   # best-effort page screenshots

    # --- Block F: multi-tenancy & billing ---------------------------------------
    billing_stripe_webhook_secret: Optional[SecretStr] = None   # whsec_...
    billing_yookassa_webhook_secret: Optional[SecretStr] = None
    partner_rate_limit_per_min: int = 30

    # --- Public demo deployment ---------------------------------------------------
    # Demo mode: anonymous visitors act as 'analyst' of the Default tenant,
    # protected by per-IP rate limits. Designed for portfolio deployments.
    demo_mode: bool = False
    metrics_public: bool = False              # expose /metrics without a key
    ip_rate_limit_per_min: int = 40           # general per-IP budget
    ip_rate_limit_analyze_per_min: int = 6    # expensive endpoint per-IP budget
    demo_max_checks_per_month: int = 200      # hard cost cap for the demo tenant

    def composite_weights(self) -> Dict[str, float]:
        return {
            "w_llm_confidence": self.w_llm_confidence,
            "w_phash_similarity": self.w_phash_similarity,
            "w_ela": self.w_ela,
            "w_exif": self.w_exif,
            "w_price": self.w_price,
        }


    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, v: str) -> str:
        v = (v or "gemini").strip().lower()
        if v not in (p.value for p in ProviderType):
            raise ValueError(
                f"Unsupported PROVIDER '{v}'. Allowed: {[p.value for p in ProviderType]}"
            )
        return v


settings = Settings()


def get_secret(secret: Optional[SecretStr]) -> Optional[str]:
    return secret.get_secret_value() if secret else None


def get_api_key_for_provider(provider_name: str) -> Optional[str]:
    """Single source of truth for provider -> API key resolution."""
    if provider_name == ProviderType.GROK:
        return get_secret(settings.grok_api_key)
    return get_secret(settings.gemini_api_key)


# Cached LLM providers keyed by provider name (multi-provider ready).
_provider_cache: Dict[str, VisionProvider] = {}


def get_llm_provider(provider_name: str) -> VisionProvider:
    """Get or lazily create a vision provider. Raises LookupError without key."""
    name = ProviderType((provider_name or settings.provider).strip().lower())
    if name.value not in _provider_cache:
        api_key = get_api_key_for_provider(name.value)
        if not api_key:
            raise LookupError(f"API key for provider '{name.value}' is not configured")
        _provider_cache[name.value] = create_provider(name.value, api_key)
    return _provider_cache[name.value]


def reset_provider_cache() -> None:
    """Clear cached providers (used by tests)."""
    _provider_cache.clear()
