"""Block C tests: cron scheduling, dedup TTL, WB search parser."""

import base64
import io
import json
from datetime import datetime

import pytest
from PIL import Image


def _png(color=(50, 100, 150)) -> bytes:
    img = Image.new("RGB", (64, 64))
    c0, c1, c2 = color
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), ((c0 + x) % 256, (c1 + y) % 256, (c2 + x + y) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- cron scheduling ---------------------------------------------------------------


def test_compute_next_run_at_valid_cron():
    from app.services.discovery_engine import compute_next_run_at

    nxt = compute_next_run_at("0 7 * * *")
    parsed = datetime.strptime(nxt, "%Y-%m-%d %H:%M:%S")
    assert parsed > datetime.utcnow()


def test_compute_next_run_at_invalid_cron_falls_back():
    from app.services.discovery_engine import compute_next_run_at

    nxt = compute_next_run_at("not a cron")
    assert len(nxt) == 19  # falls back to +24h instead of raising


# --- dedup TTL ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_dedup_ttl_by_verdict(client):
    import aiosqlite

    from app.database import (
        DB_PATH,
        create_brand_watch,
        listing_needs_recheck,
        update_listing_analysis,
        upsert_listing,
    )

    wid = await create_brand_watch(
        "TTLBrand", "kw1", "WB", "0 7 * * *", 24,
        json.dumps([base64.b64encode(_png()).decode()]),
    )
    url = "https://www.wildberries.ru/catalog/123/detail.aspx"

    listing_id, created = await upsert_listing(wid, url)
    assert created is True
    # Never analyzed → needs recheck regardless of TTL.
    assert await listing_needs_recheck(wid, url, 7, 2, 1) is True

    await update_listing_analysis(listing_id, "ОРИГИНАЛ", 90)

    # Just analyzed ОРИГИНАЛ → within the 7-day TTL → skip.
    assert await listing_needs_recheck(wid, url, 7, 2, 1) is False
    # Zero TTL → always recheck.
    assert await listing_needs_recheck(wid, url, 0, 0, 0) is True

    # Re-finding the same URL must NOT duplicate the row.
    _, created_again = await upsert_listing(wid, url, title="updated title")
    assert created_again is False

    # Backdate beyond the suspicious TTL (2 days); switching the stored verdict
    # to ПОДОЗРИТЕЛЬНО makes its shorter TTL apply → recheck again.
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE discovery_listings SET last_checked_at = datetime('now', '-3 days'), "
            "verdict = 'ПОДОЗРИТЕЛЬНО' WHERE id = ?",
            (listing_id,),
        )
        await db.commit()
    assert await listing_needs_recheck(wid, url, 7, 2, 1) is True


@pytest.mark.asyncio
async def test_get_due_watches_respects_next_run(client):
    from app.database import create_brand_watch, get_due_watches, set_watch_run_state

    wid = await create_brand_watch("DueBrand", "kw", "WB", "0 7 * * *", 24, json.dumps([]))
    now = "2999-01-01 00:00:00"
    due = await get_due_watches(now, limit=10)
    assert any(w["id"] == wid for w in due)          # never scheduled yet → due

    await set_watch_run_state(wid, next_run_at="2999-12-31 23:59:59")
    due = await get_due_watches(now, limit=10)
    assert not any(w["id"] == wid for w in due)


# --- WB search parser ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_wildberries_parses_api(monkeypatch):
    from app.services.discovery import search_parsers

    payload = {
        "data": {
            "products": [
                {"id": 111, "name": "Fake Sneakers", "salePriceU": 199900,
                 "supplier": "ShadyLLC"},
                {"id": 222, "name": "Another One", "salePriceU": 50000},
                {"id": None},  # malformed entry skipped
            ]
        }
    }

    class FakeResponse:
        status_code = 200

        def json(self):
            return payload

    async def fake_safe_get(url, **kwargs):
        assert "search.wb.ru" in url and "query=sneakers" in url
        return FakeResponse()

    monkeypatch.setattr(search_parsers, "safe_get", fake_safe_get)

    listings = await search_parsers.search_wildberries("sneakers", limit=5)
    assert len(listings) == 2
    first = listings[0]
    assert first["url"].endswith("/catalog/111/detail.aspx")
    assert first["sku"] == "111"
    assert first["price"] == pytest.approx(1999.0)
    assert first["seller"] == "ShadyLLC"


def _png_unused():  # keep helper import used for parity with e2e module
    return _png()
