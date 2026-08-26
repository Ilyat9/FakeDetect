"""Multi-tenancy service (Block F): authentication, roles, quotas.

Auth model:
- ``X-API-Key`` header → lookup by SHA-256 in ``api_keys`` (per-tenant, with role);
- legacy master key (settings.API_SECRET_KEY) → Default tenant, owner;
- open mode: when no API_SECRET_KEY is configured (local dev / single-tenant),
  everything maps to the Default tenant with owner rights — keeps the existing
  frontend and tests working unchanged.

Roles: owner > admin > analyst > viewer (+ special 'legal' — evidence/statuses
only, no raw LLM output access).
"""

import hashlib
import logging
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from core.config import get_secret, settings

logger = logging.getLogger(__name__)

ROLE_RANK = {"owner": 4, "admin": 3, "analyst": 2, "viewer": 1}
LEGAL = "legal"
DEFAULT_TENANT_ID = 1


class TenantContext:
    """Resolved identity for one request."""

    __slots__ = ("tenant_id", "role", "mode", "key_id")

    def __init__(self, tenant_id: int, role: str, mode: str, key_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.role = role
        self.mode = mode          # 'api_key' | 'legacy_master' | 'open'
        self.key_id = key_id

    @property
    def is_legal(self) -> bool:
        return self.role == LEGAL


PLAN_LIMITS: Dict[str, Dict[str, int]] = {
    "free": {"max_checks_per_month": 100, "max_watches": 2, "max_users": 3},
    "pro": {"max_checks_per_month": 2000, "max_watches": 10, "max_users": 10},
    "business": {"max_checks_per_month": 20000, "max_watches": 50, "max_users": 50},
}


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


# --- authentication ---------------------------------------------------------------


async def _authenticate(raw_key: str) -> Optional[TenantContext]:
    """Resolve an X-API-Key header value into a TenantContext, or None."""
    from database import lookup_api_key, touch_api_key

    if get_secret(settings.api_secret_key) and raw_key == get_secret(settings.api_secret_key):
        return TenantContext(DEFAULT_TENANT_ID, "owner", "legacy_master")

    record = await lookup_api_key(hash_key(raw_key))
    if record:
        import asyncio

        asyncio.create_task(touch_api_key(record["id"]))
        return TenantContext(
            tenant_id=record["tenant_id"],
            role=record["role"],
            mode="api_key",
            key_id=record["id"],
        )
    return None


async def resolve_context(request: Request) -> TenantContext:
    """Resolve the tenant context for a request (raises 401/403 on failure)."""
    raw_key = request.headers.get("x-api-key") or ""

    if not raw_key:
        if get_secret(settings.api_secret_key):
            raise HTTPException(status_code=401, detail="X-API-Key header required")
        # Open/demo mode: single-tenant public deployment.
        role = "analyst" if settings.demo_mode else "owner"
        return TenantContext(DEFAULT_TENANT_ID, role, "open")

    ctx = await _authenticate(raw_key)
    if ctx is None:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return ctx


# --- authorization ----------------------------------------------------------------


async def require_ctx(
    request: Request, min_role: str = "viewer", allow_legal: bool = False
) -> TenantContext:
    """Resolve context AND enforce the role floor.

    ``allow_legal=True`` marks endpoints the 'legal' role may access
    (case statuses, evidence packs — no raw LLM output / configuration).
    """
    ctx = await resolve_context(request)

    if ctx.is_legal:
        if not allow_legal:
            raise HTTPException(
                status_code=403,
                detail="Role 'legal' has access only to case statuses and evidence packages",
            )
        return ctx

    min_rank = ROLE_RANK.get(min_role)
    role_rank = ROLE_RANK.get(ctx.role)
    if min_rank is None:
        raise HTTPException(status_code=500, detail=f"Unknown required role '{min_role}'")
    if role_rank is None or role_rank < min_rank:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{ctx.role}' is not allowed here (requires '{min_role}' or higher)",
        )
    return ctx


# --- quotas (F.3) ------------------------------------------------------------------


async def ensure_checks_quota(tenant_id: int, requested: int = 1) -> None:
    """Raise 402 with details when the monthly plan limit would be exceeded."""
    from database import count_checks_this_month, get_tenant

    tenant = await get_tenant(tenant_id)
    if not tenant or not tenant.get("is_active"):
        raise HTTPException(status_code=402, detail={
            "error": "tenant_inactive",
            "detail": "Организация деактивирована (проверьте статус подписки)",
        })
    limit = int(tenant.get("max_checks_per_month") or 0)
    used = await count_checks_this_month(tenant_id)
    if used + requested > limit:
        raise HTTPException(status_code=402, detail={
            "error": "plan_limit_exceeded",
            "limit": "checks_per_month",
            "plan": tenant.get("plan"),
            "used": used,
            "requested": requested,
            "max": limit,
            "upgrade_hint": "Увеличьте лимит: обновите тарифный план (см. биллинг)",
        })


async def ensure_watches_quota(tenant_id: int) -> None:
    from database import count_tenant_watches, get_tenant

    tenant = await get_tenant(tenant_id)
    if not tenant:
        return
    limit = int(tenant.get("max_watches") or 0)
    used = await count_tenant_watches(tenant_id)
    if used >= limit:
        raise HTTPException(status_code=402, detail={
            "error": "plan_limit_exceeded",
            "limit": "watches",
            "plan": tenant.get("plan"),
            "used": used,
            "max": limit,
            "upgrade_hint": "Обновите тарифный план для дополнительных brand watch'ей",
        })


async def ensure_users_quota(tenant_id: int) -> None:
    from database import count_api_keys, get_tenant

    tenant = await get_tenant(tenant_id)
    if not tenant:
        return
    limit = int(tenant.get("max_users") or 0)
    used = await count_api_keys(tenant_id)
    if used >= limit:
        raise HTTPException(status_code=402, detail={
            "error": "plan_limit_exceeded",
            "limit": "users",
            "plan": tenant.get("plan"),
            "used": used,
            "max": limit,
            "upgrade_hint": "Обновите тарифный план, чтобы добавить пользователей",
        })


# --- bootstrap ----------------------------------------------------------------------


async def bootstrap() -> None:
    """Startup seeding: default tenant + master key row (if configured)."""
    from database import (
        create_api_key,
        ensure_default_tenant,
        get_tenant,
        update_tenant_plan,
    )

    await ensure_default_tenant()

    # Demo deployment: hard cost cap on the shared demo tenant.
    if settings.demo_mode:
        tenant = await get_tenant(DEFAULT_TENANT_ID)
        if tenant and int(tenant.get("max_checks_per_month") or 0) > \
                settings.demo_max_checks_per_month:
            await update_tenant_plan(
                DEFAULT_TENANT_ID,
                max_checks_per_month=settings.demo_max_checks_per_month,
            )
            logger.info(
                f"Demo mode: default tenant capped at "
                f"{settings.demo_max_checks_per_month} checks/month"
            )

    master = get_secret(settings.api_secret_key)
    if master:
        inserted = await create_api_key(
            DEFAULT_TENANT_ID, hash_key(master), name="legacy-master", role="owner"
        )
        if inserted:
            logger.info("Seeded api_keys row for the legacy master key")


# --- partner API rate limiting (F.5, stricter than the internal API) ----------------

_partner_buckets: Dict[str, Any] = {}


async def partner_rate_limit(request: Request) -> TenantContext:
    """Strict auth + per-key token bucket for the partner REST API."""
    from core.resilience import TokenBucketRateLimiter

    raw_key = request.headers.get("x-api-key") or ""
    if not raw_key:
        raise HTTPException(status_code=401, detail="X-API-Key required for partner API")
    ctx = await _authenticate(raw_key)
    if ctx is None:
        raise HTTPException(status_code=403, detail="Invalid API key")

    bucket = _partner_buckets.get(raw_key)
    if bucket is None:
        bucket = TokenBucketRateLimiter(
            f"partner:{ctx.key_id}",
            capacity=settings.partner_rate_limit_per_min,
            refill_rate_per_sec=settings.partner_rate_limit_per_min / 60.0,
        )
        _partner_buckets[raw_key] = bucket
    if not await bucket.acquire(timeout=0.5):
        raise HTTPException(
            status_code=429,
            detail=f"Partner API rate limit exceeded "
                   f"({settings.partner_rate_limit_per_min}/min)",
            headers={"Retry-After": "60"},
        )
    return ctx


# --- public demo mode -----------------------------------------------------------------

_ip_buckets: Dict[str, Any] = {}


def client_ip(request: Request) -> str:
    """Client IP for rate limiting (respects the reverse-proxy header)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune_buckets() -> None:
    """Drop idle buckets so the in-memory dict cannot grow unbounded."""
    now = time.monotonic()
    stale = [k for k, b in _ip_buckets.items() if now - getattr(b, "_updated_at", now) > 3600]
    for k in stale:
        _ip_buckets.pop(k, None)


async def ip_rate_limit(request: Request, scope: str, per_min: int) -> None:
    """Per-IP token bucket for demo deployments (single-process)."""
    from core.resilience import TokenBucketRateLimiter

    ip = client_ip(request)
    key = f"{scope}:{ip}"
    bucket = _ip_buckets.get(key)
    if bucket is None:
        if len(_ip_buckets) > 10000:
            _prune_buckets()
        bucket = TokenBucketRateLimiter(
            key, capacity=per_min, refill_rate_per_sec=per_min / 60.0
        )
        _ip_buckets[key] = bucket
    if not await bucket.acquire(timeout=0.0):
        raise HTTPException(
            status_code=429,
            detail=f"Demo rate limit exceeded ({per_min}/min for this IP). "
                   f"Попробуйте позже.",
            headers={"Retry-After": "60"},
        )