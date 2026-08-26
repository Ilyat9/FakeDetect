"""Batch processing business logic (moved out of the HTTP layer)."""

import asyncio
import logging
import os
import tempfile
from typing import Dict, List

import pandas as pd

from core.config import get_api_key_for_provider, get_secret, settings
from database import (
    increment_batch_task_progress,
    save_check,
    set_batch_task_status,
)
from telegram_alerts import send_telegram_alert

logger = logging.getLogger(__name__)


async def run_batch_task(
    task_id: str,
    df: pd.DataFrame,
    reference_bytes: bytes,
    provider_name: str,
    tenant_id: int = 1,
):
    """Background batch worker. Persists progress in DB, writes xlsx report at the end."""
    from batch_processor import BatchProcessor
    from dataclasses import asdict

    results = []
    try:
        api_key = get_api_key_for_provider(provider_name)
        if not api_key:
            raise ValueError(f"API key for provider '{provider_name}' is not configured")

        # Reference image is passed as bytes — no shared temp file (fixes race condition).
        processor = BatchProcessor(
            provider_name=provider_name,
            provider_api_key=api_key,
            reference_image_bytes=reference_bytes,
        )

        semaphore = asyncio.Semaphore(3)

        async def process_one(idx: int, row: dict):
            async with semaphore:
                result = await processor.process_row(dict(row), reference_bytes, idx)
                if result:
                    result_dict = asdict(result)
                    results.append(result_dict)
                    await increment_batch_task_progress(task_id)

                    result_with_meta = {
                        **result_dict,
                        "url": row.get('url', ''),
                        "brand": row.get('brand', ''),
                        "marketplace": row.get('marketplace', ''),
                        "price_original": row.get('price_original', 0),
                        "price_suspect": row.get('price_suspect', 0),
                        "seller": row.get('seller', ''),
                        "tenant_id": tenant_id,
                    }
                    await save_check(result_with_meta)

        await asyncio.gather(*[process_one(i, row) for i, row in df.iterrows()])

        # Build the Excel report: source rows + analysis results by position.
        results_df = pd.DataFrame(results)
        output_df = pd.concat([df.reset_index(drop=True), results_df], axis=1)
        result_path = os.path.join(tempfile.gettempdir(), f"fakedetect_batch_{task_id}.xlsx")
        output_df.to_excel(result_path, index=False)

        await set_batch_task_status(task_id, "completed", result_file_path=result_path)

    except Exception as e:
        logger.exception(f"Batch task {task_id} failed: {e}")
        try:
            await set_batch_task_status(task_id, "error", error=str(e))
        except Exception:
            logger.exception(f"Failed to persist error status for task {task_id}")


async def send_batch_summary(results: List[dict], df: pd.DataFrame):
    """Send a Telegram summary after batch completion."""
    bot_token = get_secret(settings.telegram_bot_token)
    chat_id = settings.telegram_chat_id
    if not bot_token or not results:
        return

    total = len(results)
    fakes = sum(1 for r in results if r.get("verdict") == "ПОДДЕЛКА")
    suspicious = sum(1 for r in results if r.get("verdict") == "ПОДОЗРИТЕЛЬНО")

    if fakes == 0 and suspicious == 0:
        return

    originals = sum(1 for r in results if r.get("verdict") == "ОРИГИНАЛ")
    brand_name = str(df['brand'].iloc[0]) if 'brand' in df.columns and len(df) > 0 else "не указан"
    summary_text = (
        f"📊 FakeDetect — Отчёт по батчу\n\n"
        f"Бренд: {brand_name}\n"
        f"Проверено: {total} товаров\n"
        f"❌ Подделок: {fakes}\n"
        f"⚠️ Подозрительных: {suspicious}\n"
        f"✅ Оригиналов: {originals}\n"
    )

    fake_results = [r for r in results if r.get("verdict") in ("ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО")]
    sellers: Dict[str, int] = {}
    for r in fake_results:
        seller = r.get("summary", "")[:60] or r.get("url", "")[:40]
        sellers[seller] = sellers.get(seller, 0) + 1
    if sellers:
        top_sellers = sorted(sellers.items(), key=lambda x: x[1], reverse=True)[:5]
        summary_text += "\nПодозрительные источники:\n"
        for seller, count in top_sellers:
            summary_text += f"• {seller} — {count} шт.\n"

    asyncio.create_task(send_telegram_alert(
        bot_token=bot_token,
        chat_id=chat_id,
        verdict="ПОДДЕЛКА",
        confidence=int(fakes / total * 100) if total > 0 else 0,
        brand=brand_name,
        url="",
        summary=summary_text,
        image_bytes=None
    ))
