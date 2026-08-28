"""Case service (Block D): auto-create cases from checks + evidence capture."""

import asyncio
import logging
from typing import Optional

from app.core.config import settings
from app.database import (
    create_case_from_check,
    enqueue_screenshot,
    get_case_by_check,
    mark_screenshot_done,
    mark_screenshot_failed,
    mark_screenshot_processing,
)

logger = logging.getLogger(__name__)

# Cases are opened automatically for everything that is not a clean original.
CASE_TRIGGER_VERDICTS = ("ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО", "ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ")


async def ensure_case_for_check(
    check_id: int,
    url: str = "",
    reference_b64: Optional[str] = None,
    suspect_b64: Optional[str] = None,
    verdict: str = "",
    capture_screenshot: bool = False,
) -> Optional[int]:
    """Create the workflow case for a check + persist evidence artifacts.

    - Only non-original verdicts open a case;
    - idempotent (existing case returned as-is);
    - screenshot is best-effort in a background task.
    Returns the case id or None.
    """
    try:
        if verdict not in CASE_TRIGGER_VERDICTS:
            existing = await get_case_by_check(check_id)
            return existing["id"] if existing else None

        case_id = await create_case_from_check(check_id)
        if case_id <= 0:
            return None

        if reference_b64 or suspect_b64:
            from app.services.evidence_store import persist_analysis_artifacts

            persist_analysis_artifacts(check_id, url, reference_b64, suspect_b64)

        if capture_screenshot and settings.evidence_screenshots_enabled and url:
            # D-C1: queue the capture immediately at analysis time — even if the
            # browser turns out to be unavailable right now, the row's
            # requested_at is the analysis moment, and the retry worker
            # (screenshot_retry_worker.py) keeps trying with backoff instead of
            # the PDF endpoint silently capturing (and back-dating) it later.
            queued = await enqueue_screenshot(check_id, url)
            if queued:
                asyncio.create_task(_capture_now_or_leave_queued(check_id, url))

        logger.info(f"Case #{case_id} ensured for check #{check_id} ({verdict})")
        return case_id
    except Exception as e:  # noqa: BLE001
        logger.error(f"ensure_case_for_check failed for check {check_id}: {e}")
        return None


async def _capture_now_or_leave_queued(check_id: int, url: str) -> None:
    """Fast path: try the screenshot immediately (most of the time the browser
    IS available). On failure the row stays queued for screenshot_retry_worker.
    """
    await mark_screenshot_processing(check_id)
    try:
        from app.services.evidence_store import capture_page_screenshot_async

        entry = await capture_page_screenshot_async(check_id, url)
        if entry:
            await mark_screenshot_done(check_id)
        else:
            await mark_screenshot_failed(
                check_id,
                "capture returned no artifact (browser unavailable?)",
                attempts=0,
                max_attempts=settings.screenshot_queue_max_attempts,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Immediate screenshot attempt failed for check {check_id}: {e}")
        await mark_screenshot_failed(
            check_id, str(e), attempts=0,
            max_attempts=settings.screenshot_queue_max_attempts,
        )