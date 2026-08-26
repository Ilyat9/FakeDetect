"""API-key authentication dependency."""

from typing import Optional

from fastapi import Header, HTTPException

from core.config import get_secret, settings


async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Require X-API-Key on protected endpoints when API_SECRET_KEY is configured."""
    secret = get_secret(settings.api_secret_key)
    if secret is None:
        return  # auth disabled (local/dev mode)
    if not x_api_key or x_api_key != secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
