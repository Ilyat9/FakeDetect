"""Data endpoints: history, stats, whitelist (tenant-scoped, Block F)."""

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse

from core.config import MAX_IMAGE_UPLOAD_BYTES
from database import (
    add_to_whitelist,
    delete_from_whitelist,
    get_checks,
    get_stats,
    get_whitelist,
)
from routers.analysis import read_upload
from services import tenancy

logger = logging.getLogger(__name__)
router = APIRouter(tags=["data"])


@router.get("/history")
async def get_history_endpoint(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    brand: Optional[str] = None,
):
    """Get check history page with pagination (own tenant only)."""
    ctx = await tenancy.require_ctx(request, min_role="viewer")
    checks, total = await get_checks(
        limit=limit, brand=brand, offset=offset, tenant_id=ctx.tenant_id
    )
    return JSONResponse(content={
        "checks": checks,
        "total": total,
        "limit": limit,
        "offset": offset,
        "tenant_id": ctx.tenant_id,
    })


@router.get("/stats")
async def get_api_stats(request: Request):
    """Get statistics from own tenant's data."""
    ctx = await tenancy.require_ctx(request, min_role="viewer")
    stats = await get_stats(tenant_id=ctx.tenant_id)
    return JSONResponse(content=stats)


@router.post("/similar")
async def find_similar_endpoint(
    request: Request,
    image: UploadFile = File(...),
    max_distance: int = Query(8, ge=1, le=32),
    limit: int = Query(20, ge=1, le=100),
):
    """Reverse image search (Block B.1) — scoped to the caller's tenant."""
    from database import find_similar_images_tenant
    from forensics.phash import compute_phash

    ctx = await tenancy.require_ctx(request, min_role="analyst")

    image_bytes = await read_upload(image, request, MAX_IMAGE_UPLOAD_BYTES)
    phash = compute_phash(image_bytes)
    if not phash:
        raise HTTPException(status_code=400, detail="Не удалось декодировать изображение")

    matches = await find_similar_images_tenant(
        phash, tenant_id=ctx.tenant_id, max_distance=max_distance, limit=limit
    )
    return JSONResponse(content={
        "phash": phash,
        "total": len(matches),
        "matches": matches,
    })


@router.get("/whitelist")
async def get_whitelist_endpoint(request: Request, brand: Optional[str] = None):
    """Get whitelist entries (own tenant)."""
    ctx = await tenancy.require_ctx(request, min_role="viewer")
    entries = await get_whitelist(brand=brand, tenant_id=ctx.tenant_id)
    return JSONResponse(content={
        "entries": entries,
        "total": len(entries)
    })


@router.post("/whitelist")
async def add_whitelist_entry(
    request: Request,
    brand: str = Form(..., max_length=200),
    seller_name: str = Form(..., max_length=200),
    marketplace: str = Form("", max_length=50),
    note: str = Form("", max_length=500),
):
    """Add entry to whitelist (admin operation, own tenant)."""
    ctx = await tenancy.require_ctx(request, min_role="admin")
    entry_id = await add_to_whitelist(
        brand, seller_name, marketplace, note, tenant_id=ctx.tenant_id
    )
    if entry_id > 0:
        return JSONResponse(content={
            "status": "added",
            "id": entry_id
        })
    return JSONResponse(
        content={"status": "error", "message": "Failed to add entry"},
        status_code=500
    )


@router.delete("/whitelist/{entry_id}")
async def delete_whitelist_entry(request: Request, entry_id: int):
    """Delete entry from whitelist (admin operation, own tenant)."""
    ctx = await tenancy.require_ctx(request, min_role="admin")
    success = await delete_from_whitelist(entry_id, tenant_id=ctx.tenant_id)
    if success:
        return JSONResponse(content={"status": "deleted"})
    return JSONResponse(
        content={"status": "error", "message": "Entry not found"},
        status_code=404
    )
