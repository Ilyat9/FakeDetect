"""Background worker replaying analyses queued while all LLM providers were down
(Block A.6). Runs inside the FastAPI event loop; started/stopped from main.py.
"""

import asyncio
import base64
import json
import logging

from core.config import settings
from database import (
    get_due_retries,
    mark_retry_done,
    mark_retry_failed,
    mark_retry_processing,
)

logger = logging.getLogger(__name__)


async def process_pending_once() -> int:
    """Process up to 3 due queue items. Returns number processed."""
    rows = await get_due_retries(limit=3)
    for row in rows:
        request_id = row["request_id"]
        await mark_retry_processing(request_id)
        try:
            import core.llm_gateway as gateway

            payload = json.loads(row["payload_json"])
            result, _source = await gateway.analyze_resilient(
                base64.b64decode(payload["original_b64"]),
                base64.b64decode(payload["suspect_b64"]),
                payload.get("meta", {}),
            )
            await mark_retry_done(request_id, result)
            logger.info(f"Retry {request_id} completed: verdict={result.get('verdict')}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - worker must survive any failure
            logger.warning(f"Retry {request_id} failed (attempt {row['attempts'] + 1}): {e}")
            await mark_retry_failed(
                request_id,
                str(e),
                attempts=row["attempts"],
                max_attempts=settings.retry_queue_max_attempts,
            )
    return len(rows)


async def run_forever(poll_seconds: float | None = None) -> None:
    """Worker loop; cancelled on app shutdown."""
    interval = poll_seconds or settings.retry_queue_poll_seconds
    logger.info(f"Retry-queue worker started (poll every {interval}s)")
    while True:
        try:
            await process_pending_once()
        except asyncio.CancelledError:
            logger.info("Retry-queue worker stopped")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error in retry-queue worker loop")
        await asyncio.sleep(interval)
