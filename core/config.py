"""Application configuration and LLM provider management."""

import logging
from typing import Dict, Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings

from llm_provider import ProviderType, VisionProvider, create_provider

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

    class Config:
        env_file = ".env"
        case_sensitive = False

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
