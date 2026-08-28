"""D-C1 regression: the evidence screenshot must be queued at analysis time
and its real capture timestamp reported honestly — never silently swapped
for a later "generate PDF" timestamp.

- happy path: browser available -> screenshot captured promptly, PDF shows it
  as captured at/near analysis time.
- degraded path: browser unavailable -> honest "pending"/"unavailable" status,
  never a fabricated capture time.
"""

import asyncio

import pytest

from app import database
from app.database import create_batch_task  # noqa: F401 (keep import group consistent)
from app.services import case_service, evidence_store


@pytest.fixture()
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test_fakedetect.db"))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "evidence"))
    asyncio.run(database.init_db())


async def _make_check(tenant_id: int = 1) -> int:
    return await database.save_check({
        "request_id": "screenshot-timing-req",
        "brand": "ScreenshotBrand",
        "url": "https://www.wildberries.ru/catalog/1/detail.aspx",
        "seller": "Seller",
        "verdict": "ПОДДЕЛКА",
        "confidence": 90,
        "summary": "fake",
        "risk_level": "high",
        "tenant_id": tenant_id,
    })


def test_happy_path_screenshot_captured_at_analysis_time(_isolated, monkeypatch):
    captured = {}

    async def fake_capture(check_id, url):
        entry = evidence_store.save_artifact(check_id, "screenshot.png", b"FAKEPNG")
        evidence_store.finalize_manifest(check_id, [entry])
        captured["entry"] = entry
        return entry

    monkeypatch.setattr(evidence_store, "capture_page_screenshot_async", fake_capture)

    async def go():
        check_id = await _make_check()
        await case_service._capture_now_or_leave_queued(check_id, "https://example.com/x")
        return check_id

    check_id = asyncio.run(go())

    assert captured, "screenshot capture should have run promptly"
    status = asyncio.run(evidence_store.get_screenshot_status(check_id, analyzed_at=None))
    assert status["status"] == "captured"
    assert status["captured_at"] == captured["entry"]["saved_at"]


def test_degraded_path_honest_pending_then_unavailable(_isolated, monkeypatch):
    async def fake_capture_fails(check_id, url):
        return None  # simulates browser/Playwright unavailable

    monkeypatch.setattr(evidence_store, "capture_page_screenshot_async", fake_capture_fails)

    async def go():
        check_id = await _make_check()
        await case_service.enqueue_screenshot(check_id, "https://example.com/x")
        await case_service._capture_now_or_leave_queued(check_id, "https://example.com/x")
        return check_id

    check_id = asyncio.run(go())

    # No screenshot.png was ever written — degraded path must not fabricate one.
    assert evidence_store.load_artifact(check_id, "screenshot.png") is None

    # Still inside the honesty deadline -> reported as "pending", not silently missing.
    status = asyncio.run(evidence_store.get_screenshot_status(check_id, analyzed_at=None))
    assert status["status"] == "pending"
    assert status["captured_at"] is None

    # Force the queued request past the honesty deadline (simulates elapsed time).
    async def backdate():
        import aiosqlite

        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE screenshot_queue SET requested_at = datetime('now', '-1 day') "
                "WHERE check_id = ?",
                (check_id,),
            )
            await db.commit()

    asyncio.run(backdate())

    status_after_deadline = asyncio.run(
        evidence_store.get_screenshot_status(check_id, analyzed_at=None)
    )
    assert status_after_deadline["status"] == "unavailable"
    assert status_after_deadline["captured_at"] is None


def test_pdf_reports_late_screenshot_as_late_not_on_time(_isolated):
    from app.services.evidence_pdf import generate_evidence_pdf

    pdf_bytes = generate_evidence_pdf(
        case={"id": 1, "check_id": 1, "brand": "B", "marketplace": "WB",
              "url": "u", "seller": "s", "verdict": "ПОДДЕЛКА", "status": "DETECTED"},
        check={"confidence": 90, "checked_at": "2026-08-29 10:00:00"},
        price_history=[],
        manifest_files=[],
        screenshot_bytes=b"FAKEPNG",
        screenshot_meta={"status": "captured_late", "captured_at": "2026-08-29T11:30:00+00:00"},
    )
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 500
