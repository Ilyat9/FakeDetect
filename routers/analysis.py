"""Analysis endpoints: single image, deep marketplace analysis, image parsing."""

import asyncio
import base64
import json
import logging
import random
from io import BytesIO

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from core.config import (
    DEEP_ANALYSIS_TIMEOUT_SECONDS,
    MAX_IMAGE_UPLOAD_BYTES,
    get_api_key_for_provider,
    get_llm_provider,
    get_secret,
    settings,
)
from database import save_check
from llm_provider import ProviderType

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])


def _retry_on_failure(max_retries=3, backoff_base=1.5):
    """Retry only transient network errors; client errors fail fast."""
    transient = (httpx.TimeoutException, httpx.ConnectError, ConnectionError)

    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except transient as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_base ** (attempt + 1) + random.uniform(0, 0.5)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries} failed ({e}). "
                            f"Retrying in {wait_time:.1f}s..."
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            raise last_exception
        return wrapper
    return decorator


async def read_upload(file: UploadFile, request: Request, max_bytes: int) -> bytes:
    """Read an uploaded file enforcing the size limit (413 on exceed)."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_bytes * 2:
        raise HTTPException(status_code=413, detail="Payload Too Large")
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)"
        )
    return data


@router.post("/parse-image")
async def parse_image(url: str = Form(...)):
    """Unified marketplace image parsing (no dependency on the LLM provider)."""
    from services.marketplace_image_fetcher import parse_marketplace_image
    try:
        return await parse_marketplace_image(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/analyze")
async def analyze(
    request: Request,
    original: UploadFile = File(...),
    suspect: UploadFile = File(...),
    url: str = Form(""),
    brand: str = Form(""),
    marketplace: str = Form(""),
    price_original: int = Form(0, ge=0),
    price_suspect: int = Form(0, ge=0),
):
    try:
        provider = get_llm_provider(settings.provider)
    except LookupError:
        raise HTTPException(status_code=500, detail="API key not configured")

    if brand and len(brand) > 200:
        raise HTTPException(status_code=400, detail="Brand name too long (max 200 chars)")

    original_bytes = await read_upload(original, request, MAX_IMAGE_UPLOAD_BYTES)
    suspect_bytes = await read_upload(suspect, request, MAX_IMAGE_UPLOAD_BYTES)

    if len(original_bytes) == 0 or len(suspect_bytes) == 0:
        raise HTTPException(status_code=400, detail="Both images are required")

    try:
        result = await _retry_on_failure()(provider.analyze)(
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

        result_with_meta = {
            **result,
            "url": url,
            "brand": brand,
            "marketplace": marketplace,
            "price_original": price_original,
            "price_suspect": price_suspect
        }
        await save_check(result_with_meta)

        bot_token = get_secret(settings.telegram_bot_token)
        chat_id = settings.telegram_chat_id
        if result.get("verdict") in ("ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО") and bot_token:
            from telegram_alerts import send_telegram_alert
            asyncio.create_task(send_telegram_alert(
                bot_token=bot_token,
                chat_id=chat_id,
                verdict=result.get("verdict", ""),
                confidence=result.get("confidence", 0),
                brand=brand,
                url=url,
                summary=result.get("summary", ""),
                image_bytes=suspect_bytes
            ))

        return result
    except json.JSONDecodeError as e:
        logger.exception(f"Invalid LLM JSON response: {e}")
        raise HTTPException(status_code=502, detail="Invalid JSON response from LLM")
    except httpx.HTTPError as e:
        logger.error(f"Network error during analysis: {e}")
        raise HTTPException(status_code=502, detail="LLM provider is unavailable")

@router.post("/analyze-deep")
async def analyze_deep(
    url: str = Form(...),
    reference_image: str = Form(...),
    brand: str = Form(""),
    marketplace: str = Form(""),
    price_original: int = Form(0, ge=0),
    provider_name: str = Form(None),
):
    """Deep analysis: parse all images from a marketplace URL and aggregate results."""
    from PIL import Image
    from aggregator import ImageAggregator
    from services.browser_service import (
        PLAYWRIGHT_AVAILABLE,
        BrowserSettings,
        MinimalBrowserService,
    )

    effective_provider = (provider_name or settings.provider).strip().lower()
    try:
        effective_provider = ProviderType(effective_provider).value
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported provider '{effective_provider}'. Allowed: gemini, grok"
        )

    api_key = get_api_key_for_provider(effective_provider)
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail=f"API key for '{effective_provider}' not configured"
        )

    if brand and len(brand) > 200:
        raise HTTPException(status_code=400, detail="Brand name too long (max 200 chars)")

    try:
        reference_bytes = base64.b64decode(reference_image)
        img = Image.open(BytesIO(reference_bytes))
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img_buffer = BytesIO()
        img.save(img_buffer, format='JPEG')
        reference_bytes = img_buffer.getvalue()
    except Exception as e:
        logger.warning(f"Invalid reference image: {e}")
        raise HTTPException(status_code=400, detail="Invalid reference image")

    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail=(
                "Глубокий анализ требует Playwright. Установите: "
                "pip install playwright playwright-stealth && playwright install chromium"
            )
        )

    # Get parser with a real browser page (Ozon/Yandex/WB reviews need JS rendering).
    browser = None
    try:
        browser = MinimalBrowserService(BrowserSettings())
        await browser.start()
        page = browser.page

        from parsers.factory import get_parser
        parser = await get_parser(url, browser_page=page)

        parse_result = await asyncio.wait_for(
            parser.get_all_images(), timeout=DEEP_ANALYSIS_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Превышен таймаут парсинга страницы маркетплейса")
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Parser error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Browser launch failed: {e}")
        raise HTTPException(status_code=503, detail=f"Не удалось запустить браузер: {e}")
    finally:
        if browser:
            await browser.close()

    if parse_result.error:
        logger.error(f"Parser error: {parse_result.error}")
        raise HTTPException(status_code=502, detail=f"Error parsing images: {parse_result.error}")

    aggregator = ImageAggregator(provider_name=effective_provider, api_key=api_key)
    aggregated_result = await aggregator.analyze_all(
        parse_result,
        reference_bytes,
        {
            "brand": brand,
            "marketplace": marketplace,
            "price_original": price_original
        }
    )

    result_with_meta = {
        **aggregated_result.__dict__,
        "url": url,
        "brand": brand,
        "marketplace": marketplace,
        "price_original": price_original
    }
    await save_check(result_with_meta)

    bot_token = get_secret(settings.telegram_bot_token)
    chat_id = settings.telegram_chat_id
    if aggregated_result.final_verdict != 'ОРИГИНАЛ' and bot_token:
        from telegram_alerts import send_telegram_alert
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
            bot_token=bot_token,
            chat_id=chat_id,
            verdict=aggregated_result.final_verdict,
            confidence=aggregated_result.final_confidence,
            brand=brand,
            url=url,
            summary=summary_text,
            image_bytes=None
        ))

    return aggregated_result.__dict__



