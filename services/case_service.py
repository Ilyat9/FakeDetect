"""Case service (Block D): auto-create cases from checks + evidence capture."""

import asyncio
import logging
from typing import Optional

from core.config import settings
from database import create_case_from_check, get_case_by_check

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
            from services.evidence_store import persist_analysis_artifacts

            persist_analysis_artifacts(check_id, url, reference_b64, suspect_b64)

        if capture_screenshot and settings.evidence_screenshots_enabled and url:
            from services.evidence_store import capture_page_screenshot_async

            asyncio.create_task(capture_page_screenshot_async(check_id, url))

        logger.info(f"Case #{case_id} ensured for check #{check_id} ({verdict})")
        return case_id
    except Exception as e:  # noqa: BLE001
        logger.error(f"ensure_case_for_check failed for check {check_id}: {e}")
        return None