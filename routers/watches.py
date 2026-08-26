"""Brand watch CRUD + discovery endpoints (Block C).

Protected by the API key like other data endpoints.
"""

import base64
import json
import logging

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from core.config import MAX_IMAGE_UPLOAD_BYTES
from core.security import verify_api_key
from database import (
    create_brand_watch,
    delete_brand_watch,
    get_brand_watch,
    get_brand_watches,
    get_watch_listings,
)
from routers.analysis import read_upload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["watches"], dependencies=[Depends(verify_api_key)])


def _validate_cron(expr: str) -> str:
    try:
        CronTrigger.from_crontab(expr.strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cron expression '{expr}': {e}",
        )
    return expr.strip()


@router.post("/watches")
async def create_watch_endpoint(
    request: Request,
    brand_name: str = Form(..., max_length=200),
    keywords: str = Form(..., max_length=1000),
    marketplaces: str = Form("WB", max_length=200),
    cron_schedule: str = Form("0 7 * * *", max_length=100),
    digest_interval_hours: int = Form(24, ge=1, le=168),
    reference: UploadFile = File(...),
):
    """Create a brand watch (reference image required for comparison)."""
    cron_schedule = _validate_cron(cron_schedule)
    keywords_csv = ",".join(k.strip() for k in keywords.split(",") if k.strip())
    if not keywords_csv:
        raise HTTPException(status_code=400, detail="At least one keyword is required")

    ref_bytes = await read_upload(reference, request, MAX_IMAGE_UPLOAD_BYTES)
    try:
        from PIL import Image
        from io import BytesIO

        Image.open(BytesIO(ref_bytes)).verify()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Reference image is not a valid image")

    watch_id = await create_brand_watch(
        brand_name=brand_name,
        keywords_csv=keywords_csv,
        marketplaces_csv=marketplaces.upper(),
        cron_schedule=cron_schedule,
        digest_interval_hours=digest_interval_hours,
        reference_images_json=json.dumps([base64.b64encode(ref_bytes).decode()]),
    )
    if watch_id <= 0:
        raise HTTPException(status_code=500, detail="Failed to create watch")
    # Compute the schedule immediately so clients see next_run_at without
    # waiting for the first scheduler tick.
    from database import set_watch_run_state
    from services.discovery_engine import compute_next_run_at

    await set_watch_run_state(watch_id, next_run_at=compute_next_run_at(cron_schedule))
    return JSONResponse(content={"status": "created", "id": watch_id}, status_code=201)


@router.get("/watches")
async def list_watches(active_only: bool = True):
    watches = await get_brand_watches(active_only=active_only)
    # Do not expose raw reference image payloads in listings.
    for w in watches:
        w.pop("reference_images", None)
    return JSONResponse(content={"watches": watches, "total": len(watches)})


@router.get("/watches/{watch_id}")
async def get_watch_endpoint(watch_id: int):
    watch = await get_brand_watch(watch_id)
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    watch.pop("reference_images", None)
    return JSONResponse(content=watch)


@router.delete("/watches/{watch_id}")
async def delete_watch_endpoint(watch_id: int):
    ok = await delete_brand_watch(watch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Watch not found")
    return JSONResponse(content={"status": "deleted"})


@router.get("/watches/{watch_id}/listings")
async def watch_listings_endpoint(watch_id: int, limit: int = 100):
    if not await get_brand_watch(watch_id):
        raise HTTPException(status_code=404, detail="Watch not found")
    listings = await get_watch_listings(watch_id, limit=min(limit, 500))
    return JSONResponse(content={"listings": listings, "total": len(listings)})


@router.post("/watches/{watch_id}/run-now")
async def run_watch_now(watch_id: int):
    """Trigger an immediate scan (outside the cron schedule)."""
    watch = await get_brand_watch(watch_id)
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    import asyncio

    from services.discovery_engine import run_watch_scan

    asyncio.create_task(_run_and_log(watch_id))
    return JSONResponse(content={
        "status": "started",
        "watch_id": watch_id,
        "poll_url": f"/api/v1/watches/{watch_id}",
    })


async def _run_and_log(watch_id: int) -> None:
    try:
        from services.discovery_engine import run_watch_scan

        await run_watch_scan(watch_id)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Manual run of watch {watch_id} failed: {e}")
