import asyncio
import os
import json
import base64
import httpx
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from io import BytesIO
import pandas as pd

from llm_provider import create_provider

load_dotenv()

logger = logging.getLogger(__name__)

# Database imports
from database import (
    init_db, save_check, get_checks, is_whitelisted, get_whitelist,
    add_to_whitelist, delete_from_whitelist, get_stats
)
# Telegram alerts
from telegram_alerts import send_telegram_alert

class Settings(BaseSettings):
    provider: str = os.getenv("PROVIDER", "gemini").lower()
    gemini_api_key: Optional[str] = None
    grok_api_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()

api_key = settings.grok_api_key if settings.provider == "grok" else settings.gemini_api_key
provider = create_provider(settings.provider, api_key) if api_key else None

app = FastAPI(
    title="FakeDetect API",
    version="2.0.0",
    description="AI-детектор подделок с интеграцией Gemini 2.0 Flash Vision"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tasks_db: Dict[str, Dict[str, Any]] = {}


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    await init_db()

def retry_on_failure(max_retries=3, backoff_base=1.5):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_base ** (attempt + 1)
                        print(f"Attempt {attempt + 1}/{max_retries} failed. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
        return wrapper
    return decorator

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/health")
async def health_check():
    return JSONResponse(content={
        "status": "ok",
        "provider": settings.provider,
        "api_key_configured": bool(settings.gemini_api_key or settings.grok_api_key)
    })

async def _run_batch(
    task_id: str,
    df: pd.DataFrame,
    file_bytes: bytes,
    reference_bytes: bytes,
    provider_name: str
):
    try:
        from batch_processor import BatchProcessor
        from dataclasses import asdict
        import io, tempfile, os

        api_key = settings.grok_api_key if provider_name == "grok" else settings.gemini_api_key

        with open("temp_reference.png", "wb") as tmp:
            tmp.write(reference_bytes)
        processor = BatchProcessor(
            "temp_reference.png",
            provider_name,
            api_key
        )

        semaphore = asyncio.Semaphore(3)

        async def process_one(idx: int, row: dict):
            async with semaphore:
                result = await processor.process_row(dict(row), reference_bytes, idx)
                if result:
                    result_dict = asdict(result)
                    tasks_db[task_id]["results"].append(result_dict)
                    tasks_db[task_id]["done"] += 1

                    # Save to database
                    result_with_meta = {
                        **result_dict,
                        "url": row.get('url', ''),
                        "brand": row.get('brand', ''),
                        "marketplace": row.get('marketplace', ''),
                        "price_original": row.get('price_original', 0),
                        "price_suspect": row.get('price_suspect', 0),
                        "seller": row.get('seller', '')
                    }
                    await save_check(result_with_meta)

        await asyncio.gather(*[process_one(i, row) for i, row in df.iterrows()])

        # Cleanup temp file
        import os
        if os.path.exists("temp_reference.png"):
            os.remove("temp_reference.png")

        tasks_db[task_id]["status"] = "done"

        # Send summary Telegram alert after batch completes
        results = tasks_db[task_id]["results"]
        total = len(results)
        fakes = sum(1 for r in results if r.get("verdict") == "ПОДДЕЛКА")
        suspicious = sum(1 for r in results if r.get("verdict") == "ПОДОЗРИТЕЛЬНО")
        originals = sum(1 for r in results if r.get("verdict") == "ОРИГИНАЛ")

        if settings.telegram_bot_token and (fakes > 0 or suspicious > 0):
            brand_name = df['brand'].iloc[0] if 'brand' in df.columns and len(df) > 0 else "не указан"

            summary_text = (
                f"📊 FakeDetect — Отчёт по батчу\n\n"
                f"Бренд: {brand_name}\n"
                f"Проверено: {total} товаров\n"
                f"❌ Подделок: {fakes}\n"
                f"⚠️ Подозрительных: {suspicious}\n"
                f"✅ Оригиналов: {originals}\n"
            )

            # Top suspicious sellers if seller column exists
            fake_results = [r for r in results if r.get("verdict") in ("ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО")]
            sellers = {}
            for r in fake_results:
                seller = r.get("seller") or r.get("url", "")[:40]
                if seller:
                    sellers[seller] = sellers.get(seller, 0) + 1

            if sellers:
                top_sellers = sorted(sellers.items(), key=lambda x: x[1], reverse=True)[:5]
                summary_text += "\nПодозрительные источники:\n"
                for seller, count in top_sellers:
                    summary_text += f"• {seller} — {count} шт.\n"

            asyncio.create_task(send_telegram_alert(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                verdict="ПОДДЕЛКА",
                confidence=int(fakes / total * 100) if total > 0 else 0,
                brand=brand_name,
                url="",
                summary=summary_text,
                image_bytes=None
            ))

    except Exception as e:
        tasks_db[task_id]["status"] = "error"
        tasks_db[task_id]["error"] = str(e)

@app.post("/batch")
async def batch_process(
    file: UploadFile = File(...),
    reference: UploadFile = File(...),
    brand: str = Form(""),
    provider_name: str = Form("gemini")
):
    file_bytes = await file.read()
    reference_bytes = await reference.read()

    df = pd.read_excel(BytesIO(file_bytes))

    if 'url' not in df.columns:
        raise HTTPException(status_code=400, detail="Excel file must contain 'url' column")

    task_id = str(datetime.now().timestamp())

    tasks_db[task_id] = {
        "total": len(df),
        "done": 0,
        "status": "processing",
        "results": []
    }

    asyncio.create_task(_run_batch(task_id, df, file_bytes, reference_bytes, provider_name))

    return JSONResponse(content={
        "task_id": task_id,
        "status": "started",
        "total": len(df)
    })

@app.get("/batch/{task_id}")
async def batch_status(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")

    return JSONResponse(content=tasks_db[task_id])

@app.post("/parse-image")
async def parse_image(url: str = Form(...)):
    if provider is None:
        raise HTTPException(status_code=500, detail="API key not configured")

    if settings.provider == "gemini":
        return await parse_gemini(url)
    elif settings.provider == "grok":
        return await parse_grok(url)
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")

async def _parse_image_from_url(url: str) -> dict:
    """Shared function to parse image from any URL (direct image or marketplace)."""
    import re
    url = url.strip()

    # If URL is a direct image link — just download it
    if re.search(r'\.(jpg|jpeg|png|webp|gif)(\?.*)?$', url, re.IGNORECASE) or \
       re.search(r'wbbasket\.ru|wbstatic\.net|static\.ozon', url, re.IGNORECASE):
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                if response.status_code == 200:
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    return {
                        "image_base64": base64.b64encode(response.content).decode(),
                        "content_type": content_type
                    }
                else:
                    raise HTTPException(status_code=404, detail=f"Could not fetch image: HTTP {response.status_code}")

        except httpx.HTTPError as e:
            print(f"Failed to download direct image from {url}: {e}")
            raise HTTPException(status_code=404, detail="Could not fetch image from URL")

async def parse_gemini(url: str) -> dict:
    import re
    url = url.strip()

    # First try direct image URLs and CDN links
    try:
        return await _parse_image_from_url(url)
    except HTTPException:
        pass  # Continue to marketplace parsing

    wb_match = re.search(r'wildberries\.ru/catalog/\d+', url, re.IGNORECASE)
    if wb_match:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                html = response.text
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+\.jpg[^"\']*)["\']', html, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    if not img_url.startswith('http'):
                        img_url = f"https:{img_url}" if img_url.startswith('//') else img_url

                    img_response = await client.get(img_url, timeout=10.0)
                    return {"image_base64": base64.b64encode(img_response.content).decode(), "content_type": "image/jpeg"}

        except Exception as e:
            print(f"Gemini parse error: {e}")

    ozon_match = re.search(r'ozon\.ru/product/[\w-]+', url, re.IGNORECASE)
    if ozon_match:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                html = response.text
                img_match = re.search(r'og:image["\']?\s*:\s*["\']([^"\']+)', html, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    img_response = await client.get(img_url, timeout=10.0)
                    return {"image_base64": base64.b64encode(img_response.content).decode(), "content_type": "image/jpeg"}

        except Exception as e:
            print(f"Gemini parse error: {e}")

    ym_match = re.search(r'yandex\.ru(?:/market)?/catalog?/\d+', url, re.IGNORECASE)
    if ym_match:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                html = response.text
                img_match = re.search(r'og:image["\']?\s*:\s*["\']([^"\']+)', html, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    img_response = await client.get(img_url, timeout=10.0)
                    return {"image_base64": base64.b64encode(img_response.content).decode(), "content_type": "image/jpeg"}

        except Exception as e:
            print(f"Gemini parse error: {e}")

    raise HTTPException(status_code=404, detail="Could not extract image from URL")

async def parse_grok(url: str) -> dict:
    import re
    url = url.strip()

    # First try direct image URLs and CDN links
    try:
        return await _parse_image_from_url(url)
    except HTTPException:
        pass  # Continue to marketplace parsing

    wb_match = re.search(r'wildberries\.ru/catalog/\d+', url, re.IGNORECASE)
    if wb_match:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                html = response.text
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+\.jpg[^"\']*)["\']', html, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    if not img_url.startswith('http'):
                        img_url = f"https:{img_url}" if img_url.startswith('//') else img_url

                    img_response = await client.get(img_url, timeout=10.0)
                    return {"image_base64": base64.b64encode(img_response.content).decode(), "content_type": "image/jpeg"}

        except Exception as e:
            print(f"Grok parse error: {e}")

    ozon_match = re.search(r'ozon\.ru/product/[\w-]+', url, re.IGNORECASE)
    if ozon_match:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                html = response.text
                img_match = re.search(r'og:image["\']?\s*:\s*["\']([^"\']+)', html, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    img_response = await client.get(img_url, timeout=10.0)
                    return {"image_base64": base64.b64encode(img_response.content).decode(), "content_type": "image/jpeg"}

        except Exception as e:
            print(f"Grok parse error: {e}")

    ym_match = re.search(r'yandex\.ru(?:/market)?/catalog?/\d+', url, re.IGNORECASE)
    if ym_match:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                html = response.text
                img_match = re.search(r'og:image["\']?\s*:\s*["\']([^"\']+)', html, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    img_response = await client.get(img_url, timeout=10.0)
                    return {"image_base64": base64.b64encode(img_response.content).decode(), "content_type": "image/jpeg"}

        except Exception as e:
            print(f"Grok parse error: {e}")

    raise HTTPException(status_code=404, detail="Could not extract image from URL")

@app.post("/analyze")
async def analyze(
    original: UploadFile = File(...),
    suspect: UploadFile = File(...),
    url: str = Form(""),
    brand: str = Form(""),
    marketplace: str = Form(""),
    price_original: int = Form(0),
    price_suspect: int = Form(0)
):
    if provider is None:
        raise HTTPException(status_code=500, detail="API key not configured")

    original_bytes = await original.read()
    suspect_bytes = await suspect.read()

    if len(original_bytes) == 0 or len(suspect_bytes) == 0:
        raise HTTPException(status_code=400, detail="Both images are required")

    try:
        result = await retry_on_failure()(provider.analyze)(
            original_bytes,
            suspect_bytes,
            {
                "brand": brand,
                "marketplace": marketplace,
                "price_original": price_original,
                "price_suspect": price_suspect,
                "url": url
            }
        )

        # Save check to database
        result_with_meta = {
            **result,
            "url": url,
            "brand": brand,
            "marketplace": marketplace,
            "price_original": price_original,
            "price_suspect": price_suspect
        }
        await save_check(result_with_meta)

        # Send Telegram alert if needed
        if result.get("verdict") in ("ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО") and settings.telegram_bot_token:
            asyncio.create_task(send_telegram_alert(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                verdict=result.get("verdict", ""),
                confidence=result.get("confidence", 0),
                brand=brand,
                url=url,
                summary=result.get("summary", ""),
                image_bytes=suspect_bytes
            ))

        return result
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON response from LLM: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-deep")
async def analyze_deep(
    url: str = Form(...),
    reference_image: str = Form(...),
    brand: str = Form(""),
    marketplace: str = Form(""),
    price_original: int = Form(0)
):
    """Perform deep analysis by parsing all images from a marketplace URL."""
    import base64
    from io import BytesIO
    from PIL import Image
    from aggregator import ImageAggregator
    from database import save_check

    try:
        # Decode reference image
        reference_bytes = base64.b64decode(reference_image)

        # Validate reference image
        img = Image.open(BytesIO(reference_bytes))
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img_buffer = BytesIO()
        img.save(img_buffer, format='JPEG')
        reference_bytes = img_buffer.getvalue()

        # Get parser
        from parsers.factory import get_parser
        parser = await get_parser(url)

        # Parse all images
        parse_result = await parser.get_all_images()

        if parse_result.error:
            logger.error(f"Parser error: {parse_result.error}")
            raise HTTPException(status_code=500, detail=f"Error parsing images: {parse_result.error}")

        # Aggregate analysis
        api_key = settings.gemini_api_key if settings.provider == "gemini" else settings.grok_api_key
        aggregator = ImageAggregator(provider_name="gemini", api_key=api_key)
        aggregated_result = await aggregator.analyze_all(
            parse_result,
            reference_bytes,
            {
                "brand": brand,
                "marketplace": marketplace,
                "price_original": price_original
            }
        )

        # Prepare result for database
        result_with_meta = {
            **aggregated_result.__dict__,
            "url": url,
            "brand": brand,
            "marketplace": marketplace,
            "price_original": price_original
        }

        # Save to database
        await save_check(result_with_meta)

        # Send Telegram alert if not original
        if aggregated_result.final_verdict != 'ОРИГИНАЛ' and settings.telegram_bot_token:
            summary_text = (
                f"📊 FakeDetect — Глубокий анализ\n\n"
                f"URL: {url}\n"
                f"Бренд: {brand}\n"
                f"Вердикт: {aggregated_result.final_verdict}\n"
                f"Уверенность: {aggregated_result.final_confidence}%\n"
                f"Всего изображений: {aggregated_result.total_images}\n"
                f"Подозрительных: {aggregated_result.suspicious_count}\n\n"
                f"{aggregated_result.summary}"
            )

            asyncio.create_task(send_telegram_alert(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                verdict=aggregated_result.final_verdict,
                confidence=aggregated_result.final_confidence,
                brand=brand,
                url=url,
                summary=summary_text,
                image_bytes=None
            ))

        return aggregated_result.__dict__

    except ValueError as e:
        logger.error(f"Parser error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in analyze_deep: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history")
async def get_history(limit: int = 50, brand: Optional[str] = None):
    """Get check history from database."""
    checks = await get_checks(limit=limit, brand=brand)
    return JSONResponse(content={
        "checks": checks,
        "total": len(checks)
    })


@app.get("/stats")
async def get_api_stats():
    """Get statistics from database."""
    stats = await get_stats()
    return JSONResponse(content=stats)


@app.get("/whitelist")
async def get_whitelist_endpoint(brand: Optional[str] = None):
    """Get whitelist entries from database."""
    entries = await get_whitelist(brand=brand)
    return JSONResponse(content={
        "entries": entries,
        "total": len(entries)
    })


@app.post("/whitelist")
async def add_whitelist_entry(
    brand: str = Form(...),
    seller_name: str = Form(...),
    marketplace: str = Form(""),
    note: str = Form("")
):
    """Add entry to whitelist."""
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


@app.delete("/whitelist/{entry_id}")
async def delete_whitelist_entry(entry_id: int):
    """Delete entry from whitelist."""
    success = await delete_from_whitelist(entry_id)
    if success:
        return JSONResponse(content={"status": "deleted"})
    return JSONResponse(
        content={"status": "error", "message": "Entry not found"},
        status_code=404
    )
