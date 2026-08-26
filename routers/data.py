"""Data endpoints: history, stats, whitelist (protected by API key)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import JSONResponse

from core.security import verify_api_key
from database import (
    add_to_whitelist,
    delete_from_whitelist,
    get_checks,
    get_stats,
    get_whitelist,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["data"], dependencies=[Depends(verify_api_key)])


@router.get("/history")
async def get_history_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    brand: Optional[str] = None,
):
    """Get check history page with pagination."""
    checks, total = await get_checks(limit=limit, brand=brand, offset=offset)
    return JSONResponse(content={
        "checks": checks,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@router.get("/stats")
async def get_api_stats():
    """Get statistics from database."""
    stats = await get_stats()
    return JSONResponse(content=stats)


@router.get("/whitelist")
async def get_whitelist_endpoint(brand: Optional[str] = None):
    """Get whitelist entries from database."""
    entries = await get_whitelist(brand=brand)
    return JSONResponse(content={
        "entries": entries,
        "total": len(entries)
    })


@router.post("/whitelist")
async def add_whitelist_entry(
    brand: str = Form(..., max_length=200),
    seller_name: str = Form(..., max_length=200),
    marketplace: str = Form("", max_length=50),
    note: str = Form("", max_length=500),
):
    """Add entry to whitelist (admin operation)."""
    entry_id = await add_to_whitelist(brand, seller_name, marketplace, note)
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
async def delete_whitelist_entry(entry_id: int):
    """Delete entry from whitelist (admin operation)."""
    success = await delete_from_whitelist(entry_id)
    if success:
        return JSONResponse(content={"status": "deleted"})
    return JSONResponse(
        content={"status": "error", "message": "Entry not found"},
        status_code=404
    )
