"""Background worker replaying evidence screenshot captures that failed at
analysis time — usually because the browser/Playwright was unavailable
(Block D.1 / D-C1). Mirrors app/services/retry_worker.py's shape but is kept
separate: the payload/handler here (one URL -> one screenshot) is nothing
like the LLM retry queue's, and forcing them through one generic dispatcher
would only add indirection for two call sites.
"""

import asyncio
import logging

from app.core.config import settings
from app.database import (
    get_due_screenshots,
    mark_screenshot_done,
    mark_screenshot_failed,
    mark_screenshot_processing,
)

logger = logging.getLogger(__name__)


async def process_pending_once() -> int:
    """Process up to 3 due screenshot jobs. Returns number processed."""
    rows = await get_due_screenshots(limit=3)
    for row in rows:
        check_id = row["check_id"]
        await mark_screenshot_processing(check_id)
        try:
            from app.services.evidence_store import capture_page_screenshot_async

            entry = await capture_page_screenshot_async(check_id, row["url"])
            if entry:
                await mark_screenshot_done(check_id)
                logger.info(f"Screenshot retry succeeded for check {check_id}")
            else:
                raise RuntimeError("capture returned no artifact (browser unavailable?)")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - worker must survive any failure
            logger.warning(
                f"Screenshot retry failed for check {check_id} "
                f"(attempt {row['attempts'] + 1}): {e}"
            )
            await mark_screenshot_failed(
                check_id,
                str(e),
                attempts=row["attempts"],
                max_attempts=settings.screenshot_queue_max_attempts,
            )
    return len(rows)


async def run_forever(poll_seconds: float | None = None) -> None:
    """Worker loop; cancelled on app shutdown."""
    interval = poll_seconds or settings.screenshot_queue_poll_seconds
    logger.info(f"Screenshot-queue worker started (poll every {interval}s)")
    while True:
        try:
            await process_pending_once()
        except asyncio.CancelledError:
            logger.info("Screenshot-queue worker stopped")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error in screenshot-queue worker loop")
        await asyncio.sleep(interval)
