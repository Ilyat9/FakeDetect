"""C-C4 regression: the email digest must actually send mail when SMTP is
configured, and must refuse (loudly) rather than silently accept a
digest_email when SMTP is not configured.
"""

import asyncio

import aiosqlite
import pytest
from PIL import Image
import io

from app import database
from app.core.config import settings
from app.services import discovery_engine


def _png_bytes() -> bytes:
    img = Image.new("RGB", (32, 32), (90, 90, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _open_mode(monkeypatch):
    monkeypatch.setattr(settings, "api_secret_key", None)


def _smtp_configured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_email", "alerts@example.com")


# --- creation-time validation --------------------------------------------------------


def test_create_watch_with_digest_email_requires_smtp_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "smtp_from_email", None)

    res = client.post("/api/v1/watches", data={
        "brand_name": "EmailBrand",
        "keywords": "kw",
        "cron_schedule": "0 7 * * *",
        "digest_interval_hours": 24,
        "digest_email": "owner@brand.com",
    }, files={"reference": ("ref.png", _png_bytes(), "image/png")})
    assert res.status_code == 400
    assert "SMTP" in res.json()["detail"]


def test_create_watch_with_digest_email_rejects_bad_address(client, monkeypatch):
    _smtp_configured(monkeypatch)
    res = client.post("/api/v1/watches", data={
        "brand_name": "EmailBrand2",
        "keywords": "kw",
        "cron_schedule": "0 7 * * *",
        "digest_interval_hours": 24,
        "digest_email": "not-an-email",
    }, files={"reference": ("ref.png", _png_bytes(), "image/png")})
    assert res.status_code == 422


def test_create_watch_with_digest_email_succeeds_when_smtp_configured(client, monkeypatch):
    _smtp_configured(monkeypatch)
    res = client.post("/api/v1/watches", data={
        "brand_name": "EmailBrand3",
        "keywords": "kw",
        "cron_schedule": "0 7 * * *",
        "digest_interval_hours": 24,
        "digest_email": "owner@brand.com",
    }, files={"reference": ("ref.png", _png_bytes(), "image/png")})
    assert res.status_code == 201, res.text


# --- maybe_send_digest sending behavior -----------------------------------------------


async def _seed_watch_with_findings(digest_email: str | None) -> int:
    from app.database import create_brand_watch

    watch_id = await create_brand_watch(
        brand_name="DigestBrand", keywords_csv="kw", marketplaces_csv="WB",
        cron_schedule="0 7 * * *", digest_interval_hours=24,
        reference_images_json="[]", tenant_id=1, digest_email=digest_email,
    )
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            """INSERT INTO discovery_listings
               (watch_id, url, title, price, seller, status, verdict, confidence, last_checked_at)
               VALUES (?, 'https://wb.ru/1', 'Fake Item', 500, 'BadSeller',
                       'analyzed', 'ПОДДЕЛКА', 92, datetime('now'))""",
            (watch_id,),
        )
        await db.commit()
    return watch_id


def test_digest_sends_real_email_when_smtp_configured(client, monkeypatch):
    _smtp_configured(monkeypatch)
    sent = {}

    async def fake_send(to_email, subject, html_body, text_body):
        sent["to"] = to_email
        sent["subject"] = subject
        sent["html"] = html_body
        return True

    monkeypatch.setattr("app.email_alerts.send_digest_email", fake_send)

    watch_id = asyncio.run(_seed_watch_with_findings("owner@brand.com"))
    asyncio.run(discovery_engine.maybe_send_digest(watch_id, "DigestBrand", 24))

    assert sent["to"] == "owner@brand.com"
    assert "DigestBrand" in sent["subject"]
    assert "Fake Item" in sent["html"] or "wb.ru/1" in sent["html"]


def test_digest_warns_instead_of_silently_dropping_when_smtp_unconfigured(
    client, monkeypatch, caplog
):
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "smtp_from_email", None)

    watch_id = asyncio.run(_seed_watch_with_findings("owner@brand.com"))

    import logging

    with caplog.at_level(logging.WARNING, logger="app.services.discovery_engine"):
        asyncio.run(discovery_engine.maybe_send_digest(watch_id, "DigestBrand", 24))

    assert any(
        "digest_email" in r.message and "not sent" in r.message.lower()
        for r in caplog.records
    )
