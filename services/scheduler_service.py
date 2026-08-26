"""Discovery scheduler (Block C.1): APScheduler inside FastAPI.

One persistent tick job polls `brand_watches.next_run_at` and spawns scan
tasks for due watches — the schedule itself lives in the DB (cron expression),
so it survives restarts without a separate job-store.
"""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler = None  # type: ignore[assignment]
_running_tasks: set = set()


async def _tick() -> None:
    from database import get_due_watches

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    due = await get_due_watches(now_str, limit=settings.scheduler_due_batch)
    for watch in due:
        task = asyncio.create_task(_guarded_run(watch["id"]))
        _running_tasks.add(task)
        task.add_done_callback(_running_tasks.discard)


async def _sla_tick() -> None:
    """D.3 escalation: notify about open cases whose SLA deadline passed."""
    try:
        import json as _json

        from core.config import get_secret
        from database import get_overdue_cases, mark_escalated
        from telegram_alerts import send_telegram_alert

        overdue = await get_overdue_cases()
        if not overdue:
            return

        # Re-escalate at most once per 12h per case.
        fresh = [
            c for c in overdue
            if not c.get("last_escalated_at")
            or (
                datetime.now(timezone.utc)
                - datetime.strptime(str(c["last_escalated_at"])[:19], "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone.utc)
            ).total_seconds() > 12 * 3600
        ]
        if not fresh:
            return

        lines = [f"⏰ FakeDetect SLA: {len(fresh)} кейс(ов) просрочено:"]
        for case in fresh[:10]:
            assignee = case.get("assignee") or "не назначен"
            lines.append(
                f"• #{case['id']} [{case['status']}] {case.get('brand') or ''} "
                f"— ответственный: {assignee}\n  {case.get('url') or ''}"
            )
        text = "\n".join(lines)

        bot_token = get_secret(settings.telegram_bot_token)
        chat_id = settings.telegram_chat_id
        if bot_token and chat_id:
            await send_telegram_alert(
                bot_token=bot_token, chat_id=chat_id,
                verdict="ПОДОЗРИТЕЛЬНО", confidence=0,
                brand="SLA", url="", summary=text, image_bytes=None,
            )
        else:
            logger.warning(f"SLA escalation (Telegram not configured):\n{text}")

        await mark_escalated([c["id"] for c in fresh])
    except Exception:  # noqa: BLE001 - SLA tick must never kill the scheduler
        logger.exception("SLA escalation tick failed")


async def _guarded_run(watch_id: int) -> None:
    """Scan wrapper: a failing watch never kills the scheduler loop."""
    try:
        from services.discovery_engine import run_watch_scan

        await run_watch_scan(watch_id)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Watch #{watch_id} scan failed: {e}")
        from database import set_watch_run_state

        await set_watch_run_state(watch_id, last_status=f"error: {str(e)[:200]}")


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _tick,
        IntervalTrigger(seconds=settings.discovery_tick_seconds),
        id="discovery_tick",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _sla_tick,
        IntervalTrigger(minutes=30),
        id="sla_escalation_tick",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        f"Discovery scheduler started (tick every {settings.discovery_tick_seconds}s)"
    )


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        for task in list(_running_tasks):
            task.cancel()
        logger.info("Discovery scheduler stopped")
