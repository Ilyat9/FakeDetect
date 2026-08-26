"""Case workflow endpoints (Block D).

- status machine with validated transitions + history + comments,
- bulk transitions, SLA overdue listing,
- evidence PDF (chain of custody),
- ready-to-copy complaint text per marketplace.
"""

import base64  # noqa: F401 (kept for future artifact endpoints)
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from core.security import verify_api_key
from database import (
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
from services.evidence_pdf import generate_evidence_pdf
from services.evidence_store import get_manifest, load_artifact

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cases"], dependencies=[Depends(verify_api_key)])


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


@router.get("/cases")
async def list_cases_endpoint(
    status: str = None,
    brand: str = None,
    seller: str = None,
    limit: int = 100,
):
    cases = await list_cases(status=status, brand=brand, seller=seller,
                             limit=min(limit, 500))
    return JSONResponse(content={"cases": cases, "total": len(cases)})


@router.get("/cases/overdue")
async def overdue_cases():
    """Cases whose SLA deadline passed (escalation dashboard)."""
    overdue = await get_overdue_cases()
    return JSONResponse(content={"overdue": overdue, "total": len(overdue)})


@router.get("/cases/{case_id}")
async def get_case_endpoint(case_id: int):
    case = await get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return JSONResponse(content={
        "case": case,
        "history": await get_case_history(case_id),
        "comments": await get_case_comments(case_id),
    })


@router.post("/cases/{case_id}/transition")
async def transition_case_endpoint(case_id: int, body: TransitionRequest):
    ok, result = await transition_case(
        case_id, body.to_status, body.changed_by, body.comment or None
    )
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return JSONResponse(content={"status": "transitioned", "case": result})


@router.post("/cases/bulk-transition")
async def bulk_transition(body: BulkTransitionRequest):
    """Mass status change, e.g. all cases of one seller → COMPLAINT_FILED."""
    results = {"transitioned": [], "failed": []}
    for cid in body.case_ids:
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
async def assign_case_endpoint(case_id: int, body: AssignRequest):
    if not await get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    await assign_case(case_id, body.assignee)
    return JSONResponse(content={"status": "assigned", "assignee": body.assignee})


@router.post("/cases/{case_id}/comments")
async def add_comment_endpoint(case_id: int, body: CommentRequest):
    if not await get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    comment_id = await add_case_comment(case_id, body.author, body.text)
    return JSONResponse(content={"status": "added", "id": comment_id})


@router.get("/cases/{case_id}/comments")
async def comments_endpoint(case_id: int):
    return JSONResponse(content={"comments": await get_case_comments(case_id)})


@router.get("/cases/{case_id}/history")
async def history_endpoint(case_id: int):
    return JSONResponse(content={"history": await get_case_history(case_id)})


@router.get("/cases/{case_id}/evidence-pdf")
async def evidence_pdf_endpoint(case_id: int):
    """Legally-oriented PDF evidence pack for the case."""
    case = await get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    check = await get_check_row(case["check_id"])
    if not check:
        raise HTTPException(status_code=404, detail="Underlying check not found")

    # Best-effort screenshot at generation time when none was captured earlier.
    screenshot = load_artifact(case["check_id"], "screenshot.png")
    if not screenshot and case.get("url"):
        try:
            from services.evidence_store import capture_page_screenshot_async

            entry = await capture_page_screenshot_async(case["check_id"], case["url"])
            if entry:
                screenshot = load_artifact(case["check_id"], "screenshot.png")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Evidence screenshot unavailable for case {case_id}: {e}")

    pdf_bytes = generate_evidence_pdf(
        case=case,
        check=check,
        price_history=await get_price_history(case.get("url") or ""),
        manifest_files=get_manifest(case["check_id"]),
        screenshot_bytes=screenshot,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="evidence_case_{case_id}.pdf"'},
    )


@router.get("/cases/{case_id}/complaint")
async def complaint_endpoint(case_id: int, marketplace: str = None):
    """Ready-to-copy complaint text for the marketplace complaint form (D.2)."""
    from services.complaints import render_complaint

    case = await get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
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
        from services.complaints import resolve_template_marketplace

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