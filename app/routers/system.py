"""System endpoints: deep health-check, Prometheus metrics, retry-queue polling.

Block A.5 (observability) and A.6 (queue status visibility).
"""

import logging
import time

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app import database
from app.core.config import get_api_key_for_provider, get_llm_provider, settings
from app.core.metrics import render_metrics
from app.database import get_queue_item
from app.llm_provider import ProviderType

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


async def _check_database() -> dict:
    start = time.monotonic()
    try:
        async with aiosqlite.connect(database.DB_PATH) as db:
            cursor = await db.execute("SELECT 1")
            await cursor.fetchone()
        return {"ok": True, "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def _check_playwright() -> dict:
    """Cheap check: playwright importable. (Full browser launch is too costly
    for a health probe; covered by the load-test / smoke suite instead.)"""
    try:
        from app.services.browser_service import PLAYWRIGHT_AVAILABLE

        return {"available": bool(PLAYWRIGHT_AVAILABLE)}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)[:200]}


async def _check_providers(deep_ping: bool) -> dict:
    result = {}
    for provider_type in ProviderType:
        name = provider_type.value
        configured = bool(get_api_key_for_provider(name))
        entry: dict = {"configured": configured}
        if configured:
            from app.core.llm_gateway import get_breaker

            entry["circuit_state"] = get_breaker(name).state.value
            if deep_ping:
                try:
                    provider = get_llm_provider(name)
                    entry["ping_ok"] = bool(await provider.ping())
                except Exception as e:  # noqa: BLE001
                    entry["ping_ok"] = False
                    entry["ping_error"] = str(e)[:200]
        result[name] = entry
    return result


@router.get("/health")
async def health(deep: bool = False):
    """Dependency-aware health check.

    Default: DB connectivity + provider configuration + circuit states (cheap).
    ?deep=true additionally pings each LLM provider REST endpoint (no tokens).
    """
    db_status = await _check_database()
    providers = await _check_providers(deep_ping=deep)
    playwright = _check_playwright()

    degraded = (
        not db_status.get("ok")
        or not any(p.get("configured") for p in providers.values())
    )
    return JSONResponse(content={
        "status": "degraded" if degraded else "ok",
        "provider": settings.provider,
        "checks": {
            "database": db_status,
            "llm_providers": providers,
            "playwright": playwright,
            "retry_queue_pending": await _pending_retries(),
        },
    })


async def _pending_retries() -> int:
    from app.database import count_retry_queue

    return await count_retry_queue(status="pending")


@router.get("/metrics")
async def metrics(request: Request):
    """Prometheus exposition. Public only when METRICS_PUBLIC=true;
    otherwise requires an admin/owner key (404 for anonymous probes)."""
    from app.services import tenancy

    if not settings.metrics_public:
        try:
            ctx = await tenancy.resolve_context(request)
            from app.services.tenancy import ROLE_RANK

            if ROLE_RANK.get(ctx.role, 0) < ROLE_RANK["admin"]:
                raise HTTPException(status_code=404, detail="Not Found")
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="Not Found")
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


@router.get("/queue/{request_id}")
async def queue_status(request_id: str):
    """Poll the status of a queued analysis (202 flow)."""
    item = await get_queue_item(request_id)
    if not item:
        return JSONResponse(
            content={"detail": "Request not found in queue"},
            status_code=404,
        )
    response = {
        "request_id": item["request_id"],
        "status": item["status"],
        "attempts": item["attempts"],
        "last_error": item["last_error"],
        "created_at": item["created_at"],
    }
    if item["status"] == "done" and item.get("result"):
        response["result"] = item["result"]
    return JSONResponse(content=response)
