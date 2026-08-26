"""Analytics & dashboard endpoints (Block E).

ROI metrics for management: verdict dynamics, top violators, protected-revenue
estimate, timing (TTD/TTR) — plus PDF/PPTX export of the whole dashboard.
All endpoints are tenant-scoped, viewer role minimum.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.database import (
    get_protected_revenue,
    get_stats,
    get_timing_metrics,
    get_top_sellers,
    get_verdict_timeseries,
)
from app.services import tenancy
from app.services.dashboard_export import build_dashboard_pdf, build_dashboard_pptx

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analytics"])

GRANULARITIES = ("day", "week", "month")


async def _collect_dashboard(
    ctx, granularity: str, days: int, brand: Optional[str]
) -> dict:
    timeseries = await get_verdict_timeseries(
        granularity=granularity, days=days, brand=brand, tenant_id=ctx.tenant_id
    )
    summary = await get_stats(tenant_id=ctx.tenant_id)
    top_sellers = await get_top_sellers(limit=10, days=days, tenant_id=ctx.tenant_id)
    revenue = await get_protected_revenue(days=days, brand=brand,
                                          tenant_id=ctx.tenant_id)
    timing = await get_timing_metrics(tenant_id=ctx.tenant_id)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "granularity": granularity,
        "days": days,
        "brand": brand,
        "summary": summary,
        "timeseries": timeseries,
        "top_sellers": top_sellers,
        "protected_revenue": revenue,
        "timing": timing,
    }


@router.get("/analytics/timeseries")
async def analytics_timeseries(
    request: Request,
    granularity: str = Query("day"),
    days: int = Query(30, ge=1, le=365),
    brand: Optional[str] = None,
):
    """Verdict dynamics bucketed by day/week/month."""
    if granularity not in GRANULARITIES:
        raise HTTPException(status_code=422, detail=f"granularity must be one of {GRANULARITIES}")
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    rows = await get_verdict_timeseries(granularity, days, brand, ctx.tenant_id)
    return JSONResponse(content={"granularity": granularity, "points": rows})


@router.get("/analytics/top-sellers")
async def analytics_top_sellers(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(90, ge=1, le=365),
):
    """Top sellers by confirmed violations."""
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    return JSONResponse(content={
        "sellers": await get_top_sellers(limit, days, ctx.tenant_id)
    })


@router.get("/analytics/revenue")
async def analytics_revenue(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    brand: Optional[str] = None,
):
    """Protected-revenue estimate (with explicit disclaimer)."""
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    return JSONResponse(content=await get_protected_revenue(days, brand, ctx.tenant_id))


@router.get("/analytics/timing")
async def analytics_timing(request: Request):
    """Time-to-detection / time-to-resolution metrics."""
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    return JSONResponse(content=await get_timing_metrics(ctx.tenant_id))


@router.get("/analytics/summary")
async def analytics_summary(
    request: Request,
    granularity: str = Query("day"),
    days: int = Query(30, ge=1, le=365),
    brand: Optional[str] = None,
):
    """Everything the dashboard needs in one response."""
    if granularity not in GRANULARITIES:
        raise HTTPException(status_code=422, detail=f"granularity must be one of {GRANULARITIES}")
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    data = await _collect_dashboard(ctx, granularity, days, brand)
    return JSONResponse(content=data)


@router.get("/analytics/export.pdf")
async def export_pdf(
    request: Request,
    granularity: str = Query("day"),
    days: int = Query(30, ge=1, le=365),
    brand: Optional[str] = None,
):
    """Management-ready PDF report of the dashboard."""
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    data = await _collect_dashboard(ctx, granularity, days, brand)
    pdf_bytes = build_dashboard_pdf(data)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="fakedetect_dashboard_{stamp}.pdf"'},
    )


@router.get("/analytics/export.pptx")
async def export_pptx(
    request: Request,
    granularity: str = Query("day"),
    days: int = Query(30, ge=1, le=365),
    brand: Optional[str] = None,
):
    """PPTX deck of the dashboard for management presentations."""
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    data = await _collect_dashboard(ctx, granularity, days, brand)
    pptx_bytes = build_dashboard_pptx(data)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=pptx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
        headers={"Content-Disposition": f'attachment; filename="fakedetect_dashboard_{stamp}.pptx"'},
    )