"""Block D tests: SLA escalation, evidence PDF generation, complaint texts."""

import aiosqlite
import uuid

import pytest
from pydantic import SecretStr

from app.core import llm_gateway as gateway
from app.core.config import settings
from app.database import DB_PATH
from tests.test_cases import _make_check, _first_case, fake_llm  # noqa: F401


@pytest.mark.asyncio
async def test_overdue_detection_and_escalation_once(client, fake_llm, monkeypatch):
    tag, _rid = _make_check(client)
    cid = _first_case(client, f"CaseBrand-{tag}")["id"]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE cases SET sla_deadline = datetime('now', '-1 hour') WHERE id = ?",
            (cid,),
        )
        await db.commit()

    overdue = client.get("/api/v1/cases/overdue").json()
    assert any(c["id"] == cid for c in overdue["overdue"])

    sent = {"n": 0}

    async def fake_alert(**kwargs):
        sent["n"] += 1
        return True

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("t"))
    monkeypatch.setattr(settings, "telegram_chat_id", "1")
    monkeypatch.setattr("app.telegram_alerts.send_telegram_alert", fake_alert)

    from app.services.scheduler_service import _sla_tick

    await _sla_tick()
    assert sent["n"] == 1
    await _sla_tick()
    assert sent["n"] == 1  # escalation is throttled to once per window


def test_evidence_pdf_generated(client, fake_llm):
    tag, _rid = _make_check(client)
    cid = _first_case(client, f"CaseBrand-{tag}")["id"]

    res = client.get(f"/api/v1/cases/{cid}/evidence-pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:5] == b"%PDF-"
    assert len(res.content) > 1000


def test_complaint_rendering_per_marketplace(client, fake_llm):
    tag, _rid = _make_check(client)
    cid = _first_case(client, f"CaseBrand-{tag}")["id"]

    for mp in ("WB", "Ozon", "Yandex"):
        r = client.get(f"/api/v1/cases/{cid}/complaint", params={"marketplace": mp})
        assert r.status_code == 200, (mp, r.text)
        text = r.json()["text"]
        assert "CaseBrand" in text
        assert "wildberries.ru/catalog/" in text
        assert "SHA-256" in text

    # Unknown marketplace falls back to the generic template instead of failing.
    r = client.get(f"/api/v1/cases/{cid}/complaint",
                   params={"marketplace": "AliExpress"})
    assert r.status_code == 200
    assert r.json()["marketplace"] == "generic"


@pytest.mark.asyncio
async def test_original_verdict_does_not_open_case(client, fake_llm, monkeypatch):
    """Only non-original verdicts open workflow cases."""
    async def original_result(orig, sus, meta, preferred_provider=None):
        return (
            {"verdict": "ОРИГИНАЛ", "confidence": 95, "summary": "ok",
             "risk_level": "low", "indicators": []},
            {"provider": "gemini", "verdict_source": "llm_analysis"},
        )

    monkeypatch.setattr(gateway, "analyze_resilient", original_result)

    res = client.post("/api/v1/analyze", files={
        "original": ("o.png", _png_bytes((1, 2, 3)), "image/png"),
        "suspect": ("s.png", _png_bytes((4, 5, 6)), "image/png"),
    }, headers={"X-Request-ID": f"orig-{uuid.uuid4().hex[:8]}"})
    assert res.status_code == 200

    from app.database import get_case_by_check

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT MAX(id) FROM checks")
        newest_check_id = (await cursor.fetchone())[0]
    assert await get_case_by_check(newest_check_id) is None


def _png_bytes(color):
    import io as _io

    from PIL import Image

    img = Image.new("RGB", (64, 64))
    c0, c1, c2 = color
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), ((c0 + x) % 256, (c1 + y) % 256, (c2 + x + y) % 256))
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
