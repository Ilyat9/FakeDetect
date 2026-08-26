"""Partner REST API (Block F.5).

Strict per-tenant API keys (no open-mode fallback), tighter rate limits and a
minimal surface for embedding FakeDetect into clients' internal systems.
Interactive OpenAPI docs are generated automatically at /docs.
"""

import asyncio
import base64
import uuid
import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import MAX_IMAGE_UPLOAD_BYTES, get_api_key_for_provider, get_secret, settings
from app.database import cache_get_result, cache_put_result, get_tenant, save_check
from app.services import tenancy

logger = logging.getLogger(__name__)
router = APIRouter(tags=["partner"])


async def _run_analysis(ctx, original_bytes: bytes, suspect_bytes: bytes,
                        meta: dict, rid: str) -> dict:
    """Shared partner analysis path (same resilient engine as /analyze)."""
    from app.core import llm_gateway as gateway
    from app.core.deadline import Deadline, reset_deadline, set_deadline
    from app.models.schemas import AnalysisResult

    deadline = Deadline(settings.request_timeout_budget_seconds)
    token = set_deadline(deadline)
    try:
        try:
            result, source = await asyncio.wait_for(
                gateway.analyze_resilient(original_bytes, suspect_bytes, meta),
                timeout=deadline.remaining(),
            )
        except gateway.AllOutputsInvalidError:
            result = AnalysisResult.manual_review(
                "Модели вернули невалидный ответ; требуется ручная проверка"
            ).model_dump()
            source = {"verdict_source": "manual_review_fallback"}
        except gateway.AllProvidersDownError:
            # Partners poll the same result endpoint after retry-queue replay;
            # enqueue like the internal API does.
            from app.database import enqueue_retry

            await enqueue_retry(rid, {
                "original_b64": base64.b64encode(original_bytes).decode(),
                "suspect_b64": base64.b64encode(suspect_bytes).decode(),
                "meta": meta,
            })
            raise HTTPException(status_code=202, detail={
                "status": "queued",
                "request_id": rid,
                "poll_url": f"/api/v1/partner/checks/{rid}",
            })
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Analysis timeout budget exceeded")
    finally:
        reset_deadline(token)

    result.update({
        **source,
        "url": meta.get("url", ""),
        "brand": meta.get("brand", ""),
        "marketplace": meta.get("marketplace", ""),
        "request_id": rid,
        "tenant_id": ctx.tenant_id,
    })
    await save_check(result)
    await cache_put_result(rid, result, ttl_hours=settings.idempotency_ttl_hours)
    return result


@router.post("/partner/checks")
async def partner_create_check(
    request: Request,
    original: UploadFile = File(...),
    suspect: UploadFile = File(...),
    brand: str = Form("", max_length=200),
    url: str = Form("", max_length=1000),
    marketplace: str = Form("", max_length=50),
):
    """Run an authenticity check (consumes the tenant's monthly quota)."""
    ctx = await tenancy.partner_rate_limit(request)
    await tenancy.ensure_checks_quota(ctx.tenant_id, requested=1)

    if not (get_api_key_for_provider(settings.provider)
            or get_api_key_for_provider("gemini")
            or get_api_key_for_provider("grok")):
        raise HTTPException(status_code=500, detail="LLM API key not configured")

    rid = uuid.uuid4().hex
    original_bytes = await original.read()
    suspect_bytes = await suspect.read()
    if not original_bytes or not suspect_bytes:
        raise HTTPException(status_code=400, detail="Both images are required")

    meta = {"brand": brand, "marketplace": marketplace, "url": url}
    result = await _run_analysis(ctx, original_bytes, suspect_bytes, meta, rid)
    return JSONResponse(content=result)


@router.get("/partner/checks/{request_id}")
async def partner_get_check(request: Request, request_id: str):
    """Fetch a stored verdict by request id (tenant-scoped)."""
    ctx = await tenancy.partner_rate_limit(request)
    cached = await cache_get_result(
        request_id, ttl_hours=settings.idempotency_ttl_hours
    )
    if not cached or cached.get("tenant_id") != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Check not found")
    return JSONResponse(content=cached)


@router.get("/partner/stats")
async def partner_stats(request: Request):
    """Tenant-scoped counters + current plan usage."""
    ctx = await tenancy.partner_rate_limit(request)
    from app.database import count_checks_this_month, get_stats

    tenant = await get_tenant(ctx.tenant_id) or {}
    used = await count_checks_this_month(ctx.tenant_id)
    stats = await get_stats(tenant_id=ctx.tenant_id)
    return JSONResponse(content={
        "stats": stats,
        "plan": tenant.get("plan"),
        "quota": {
            "checks_used_this_month": used,
            "checks_max_per_month": tenant.get("max_checks_per_month"),
        },
    })