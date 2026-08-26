"""Batch processing endpoints."""

import asyncio
import logging
import os
import uuid
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from core.config import MAX_EXCEL_UPLOAD_BYTES, MAX_IMAGE_UPLOAD_BYTES
from database import (
    create_batch_task,
    get_batch_task,
    get_batch_task_result_path,
)
from llm_provider import ProviderType
from routers.analysis import read_upload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["batch"])


@router.post("/batch")
async def batch_process(
    request: Request,
    file: UploadFile = File(...),
    reference: UploadFile = File(...),
    brand: str = Form(""),
    provider_name: str = Form("gemini"),
):
    from services.batch_service import run_batch_task

    try:
        provider = ProviderType(provider_name.strip().lower())  # validate -> 422
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported provider '{provider_name}'. Allowed: gemini, grok"
        )

    file_bytes = await read_upload(file, request, MAX_EXCEL_UPLOAD_BYTES)
    reference_bytes = await read_upload(reference, request, MAX_IMAGE_UPLOAD_BYTES)

    df = pd.read_excel(BytesIO(file_bytes))
    if 'url' not in df.columns:
        raise HTTPException(status_code=400, detail="Excel file must contain 'url' column")

    # uuid4: unpredictable ids protect against enumeration.
    task_id = str(uuid.uuid4())
    await create_batch_task(task_id, len(df))

    asyncio.create_task(run_batch_task(task_id, df, reference_bytes, provider_name.strip().lower()))

    return JSONResponse(content={
        "task_id": task_id,
        "status": "started",
        "total": len(df)
    })


@router.get("/batch/{task_id}")
async def batch_status(task_id: str):
    task = await get_batch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return JSONResponse(content={
        "task_id": task["id"],
        "total": task["total"],
        "done": task["done"],
        "status": task["status"],   # processing | completed | error
        "error": task["error"],
    })


@router.get("/batch/{task_id}/download")
async def batch_download(task_id: str):
    path = await get_batch_task_result_path(task_id)
    task = await get_batch_task(task_id)
    if not task or task["status"] != "completed" or not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Result file not available")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"fakedetect_batch_{task_id[:8]}.xlsx",
    )
