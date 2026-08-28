"""Case workflow endpoints (Block D).

- status machine with validated transitions + history + comments,
- bulk transitions, SLA overdue listing,
- evidence PDF (chain of custody),
- ready-to-copy complaint text per marketplace.
"""

import base64  # noqa: F401 (kept for future artifact endpoints)
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.database import (
    add_case_comment,
    assign_case,
    get_case,
    get_case_comments,
    get_case_history,
    get_check_row,
    get_overdue_cases,
    get_price_history,
    list_cases,
    transition_case,
)
from app.services import tenancy
from app.services.evidence_pdf import generate_evidence_pdf
from app.services.evidence_store import get_manifest, load_artifact

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cases"])


class TransitionRequest(BaseModel):
    to_status: str = Field(..., max_length=40)
    changed_by: str = Field("user", max_length=100)
    comment: str = Field("", max_length=2000)


class CommentRequest(BaseModel):
    author: str = Field("user", max_length=100)
    text: str = Field(..., min_length=1, max_length=4000)


class BulkTransitionRequest(BaseModel):
    case_ids: list[int]
    to_status: str = Field(..., max_length=40)
    changed_by: str = Field("user", max_length=100)
    comment: str = Field("", max_length=2000)


class AssignRequest(BaseModel):
    assignee: str = Field(..., max_length=100)


def _ensure_tenant_case(case: dict, ctx) -> None:
    tenancy.ensure_owned(case, ctx, label="Case")


@router.get("/cases")
async def list_cases_endpoint(
    request: Request,
    status: str = None,
    brand: str = None,
    seller: str = None,
    limit: int = 100,
):
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    cases = await list_cases(status=status, brand=brand, seller=seller,
                             limit=min(limit, 500), tenant_id=ctx.tenant_id)
    return JSONResponse(content={"cases": cases, "total": len(cases)})


@router.get("/cases/overdue")
async def overdue_cases(request: Request):
    """Cases whose SLA deadline passed (escalation dashboard)."""
    ctx = await tenancy.require_ctx(request, min_role="admin")
    overdue = [
        c for c in await get_overdue_cases() if c["tenant_id"] == ctx.tenant_id
    ]
    return JSONResponse(content={"overdue": overdue, "total": len(overdue)})


@router.get("/cases/{case_id}")
async def get_case_endpoint(request: Request, case_id: int):
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)
    return JSONResponse(content={
        "case": case,
        "history": await get_case_history(case_id),
        "comments": await get_case_comments(case_id),
    })


@router.post("/cases/{case_id}/transition")
async def transition_case_endpoint(
    request: Request, case_id: int, body: TransitionRequest
):
    ctx = await tenancy.require_ctx(request, min_role="analyst")
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)
    ok, result = await transition_case(
        case_id, body.to_status, body.changed_by, body.comment or None
    )
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return JSONResponse(content={"status": "transitioned", "case": result})


@router.post("/cases/bulk-transition")
async def bulk_transition(request: Request, body: BulkTransitionRequest):
    """Mass status change, e.g. all cases of one seller → COMPLAINT_FILED."""
    ctx = await tenancy.require_ctx(request, min_role="analyst")
    results = {"transitioned": [], "failed": []}
    for cid in body.case_ids:
        case = await get_case(cid)
        _ensure_tenant_case(case, ctx)
        ok, result = await transition_case(
            cid, body.to_status, body.changed_by, body.comment or None
        )
        (results["transitioned"] if ok else results["failed"]).append(
            {"case_id": cid, **({} if ok else {"error": result})}
        )
    return JSONResponse(content={
        "to_status": body.to_status,
        "transitioned": len(results["transitioned"]),
        "failed": results["failed"],
    })


@router.post("/cases/{case_id}/assign")
async def assign_case_endpoint(request: Request, case_id: int, body: AssignRequest):
    ctx = await tenancy.require_ctx(request, min_role="analyst")
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)
    await assign_case(case_id, body.assignee)
    return JSONResponse(content={"status": "assigned", "assignee": body.assignee})


@router.post("/cases/{case_id}/comments")
async def add_comment_endpoint(request: Request, case_id: int, body: CommentRequest):
    ctx = await tenancy.require_ctx(request, min_role="analyst")
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)
    comment_id = await add_case_comment(case_id, body.author or ctx.role, body.text)
    return JSONResponse(content={"status": "added", "id": comment_id})


@router.get("/cases/{case_id}/comments")
async def comments_endpoint(request: Request, case_id: int):
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)
    return JSONResponse(content={"comments": await get_case_comments(case_id)})


@router.get("/cases/{case_id}/history")
async def history_endpoint(request: Request, case_id: int):
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)
    return JSONResponse(content={"history": await get_case_history(case_id)})


@router.get("/cases/{case_id}/evidence-pdf")
async def evidence_pdf_endpoint(request: Request, case_id: int):
    """Legally-oriented PDF evidence pack for the case (legal role allowed)."""
    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)

    check = await get_check_row(case["check_id"])
    if not check:
        raise HTTPException(status_code=404, detail="Underlying check not found")

    # D-C1: never capture live here — that used to silently back-date the
    # screenshot to "PDF generation time". Report the real, queued/retried
    # capture state instead (see screenshot_retry_worker.py).
    from app.services.evidence_store import get_screenshot_status

    screenshot = load_artifact(case["check_id"], "screenshot.png")
    screenshot_meta = await get_screenshot_status(
        case["check_id"], analyzed_at=check.get("checked_at")
    )

    pdf_bytes = generate_evidence_pdf(
        case=case,
        check=check,
        price_history=await get_price_history(case.get("url") or ""),
        manifest_files=get_manifest(case["check_id"]),
        screenshot_bytes=screenshot,
        screenshot_meta=screenshot_meta,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="evidence_case_{case_id}.pdf"'},
    )


@router.get("/cases/{case_id}/complaint")
async def complaint_endpoint(
    request: Request, case_id: int, marketplace: str = None
):
    """Ready-to-copy complaint text for the marketplace complaint form (D.2)."""
    from app.services.complaints import render_complaint

    ctx = await tenancy.require_ctx(request, min_role="viewer", allow_legal=True)
    case = await get_case(case_id)
    _ensure_tenant_case(case, ctx)
    check = await get_check_row(case["check_id"]) or {}

    mp = marketplace or case.get("marketplace") or ""
    indicators = []
    if check.get("ela_flag"):
        indicators.append({
            "factor": "ELA",
            "detail": f"Error Level Analysis {check.get('ela_score')} — "
                      f"признаки редактирования изображения",
        })
    for f in _safe_load(check.get("exif_flags")) or []:
        indicators.append({"factor": f.get("factor", "EXIF"),
                           "detail": f.get("detail", "")})

    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "marketplace_name": mp or "маркетплейс",
        "brand": case.get("brand") or "",
        "url": case.get("url") or "",
        "seller": case.get("seller") or "",
        "price": check.get("price_suspect"),
        "verdict": case.get("verdict") or "",
        "confidence": check.get("confidence") or 0,
        "final_score": check.get("final_score"),
        "indicators": indicators,
        "evidence_files": get_manifest(case["check_id"]),
    }

    try:
        text = render_complaint(mp, context)
        from app.services.complaints import resolve_template_marketplace

        used_mp = resolve_template_marketplace(mp)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Complaint rendering failed for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate complaint")

    return JSONResponse(content={
        "marketplace": used_mp,
        "text": text,
        "note": ("Публичного API подачи брендовых жалоб у площадок нет — "
                 "скопируйте текст в форму площадки вручную."),
    })


def _safe_load(raw):
    import json as _json

    if not raw:
        return None
    if isinstance(raw, list):
        return raw
    try:
        return _json.loads(raw)
    except (TypeError, ValueError):
        return None