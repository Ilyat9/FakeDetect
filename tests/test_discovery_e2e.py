"""Block C e2e: full discovery scan cycle with mocked search + LLM."""

import base64
import io
import json
import uuid

import pytest
from PIL import Image
from pydantic import SecretStr

from app.core import llm_gateway as gateway
from app.core.config import settings


def _png(color=(50, 100, 150)) -> bytes:
    img = Image.new("RGB", (64, 64))
    c0, c1, c2 = color
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), ((c0 + x) % 256, (c1 + y) % 256, (c2 + x + y) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_full_discovery_cycle_with_dedup(client, monkeypatch):
    from app.database import (
        create_brand_watch,
        get_recent_findings,
        get_watch_listings,
    )

    # monkeypatch, NOT direct assignment: a leaked gemini_api_key made
    # test_analyze_without_api_key (test_api.py) pass auth setup downstream
    # and return 202 instead of 500 — order-dependent.
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))

    # Unique per run: discovery dedupes by URL/SKU in the session-shared DB,
    # so hardcoded ids made this test order-dependent (flake).
    run_id = uuid.uuid4().hex[:8]
    listings = [
        {"url": f"https://www.wildberries.ru/catalog/77{run_id}/detail.aspx",
         "sku": f"77{run_id}", "title": "Fake Watch", "price": 1500.0, "seller": "ScamCo"},
        {"url": f"https://www.wildberries.ru/catalog/88{run_id}/detail.aspx",
         "sku": f"88{run_id}", "title": "Original Watch", "price": 30000.0, "seller": "AuthStore"},
    ]

    async def fake_search(marketplace, keyword, limit, browser_page=None):
        return [dict(l) for l in listings]

    monkeypatch.setattr(
        "app.services.discovery.search_parsers.search_marketplace", fake_search
    )
    monkeypatch.setattr("app.services.browser_service.PLAYWRIGHT_AVAILABLE", False)

    async def fake_fetch(url):
        # Distinct image per URL: identical photos would legitimately collapse
        # into the B.1 pHash fast path and skip the LLM for the 2nd listing.
        seed = sum(ord(ch) for ch in url)
        img_bytes = _png((seed % 256, (seed * 7) % 256, (seed * 13) % 256))
        return {"image_base64": base64.b64encode(img_bytes).decode(),
                "content_type": "image/png"}

    monkeypatch.setattr(
        "app.services.marketplace_image_fetcher.parse_marketplace_image", fake_fetch
    )

    llm_calls = {"n": 0}

    async def fake_resilient(orig, sus, meta, preferred_provider=None):
        llm_calls["n"] += 1
        return (
            {"verdict": "ПОДОЗРИТЕЛЬНО", "confidence": 55, "summary": "borderline",
             "risk_level": "medium", "indicators": []},
            {"provider": "gemini", "verdict_source": "llm_analysis",
             "prompt_version": "v1", "prompt_hash": "h"},
        )

    async def no_consensus(result, provider, o, s, m):
        return result, {"consensus": "second_opinion_unavailable"}

    monkeypatch.setattr(gateway, "analyze_resilient", fake_resilient)
    monkeypatch.setattr(gateway, "run_consensus", no_consensus)

    sent = {"digests": []}

    async def fake_alert(**kwargs):
        sent["digests"].append(kwargs["summary"])
        return True

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("t"))
    monkeypatch.setattr(settings, "telegram_chat_id", "42")
    monkeypatch.setattr("app.telegram_alerts.send_telegram_alert", fake_alert)

    wid = await create_brand_watch(
        "WatchBrand", "watch kw", "WB", "0 */6 * * *", 24,
        json.dumps([base64.b64encode(_png((200, 30, 30))).decode()]),
    )

    from app.services.discovery_engine import run_watch_scan

    stats = await run_watch_scan(wid)
    assert stats["status"] == "ok"
    assert stats["analyzed"] == 2
    assert llm_calls["n"] == 2

    rows = await get_watch_listings(wid)
    assert {r["status"] for r in rows} <= {"analyzed"}
    assert {r["verdict"] for r in rows} == {"ПОДОЗРИТЕЛЬНО"}
    assert all(r["last_checked_at"] for r in rows)

    findings = await get_recent_findings(wid, since_hours=24)
    assert len(findings) >= 1

    assert sent["digests"], "expected at least one digest"
    assert "WatchBrand" in sent["digests"][0]
    assert "ПОДОЗРИТЕЛЬНО" in sent["digests"][0]

    # Second scan immediately after: both listings inside the suspicious TTL
    # (2 days) → nothing re-analyzed, no new LLM spend.
    calls_before = llm_calls["n"]
    stats2 = await run_watch_scan(wid)
    assert stats2["skipped"] == 2
    assert stats2["analyzed"] == 0
    assert llm_calls["n"] == calls_before


def test_digest_text_format():
    from app.services.discovery_engine import build_digest_text

    text = build_digest_text("Nike", [
        {"url": "https://x/1", "title": "t", "price": 1999.0, "seller": "S",
         "verdict": "ПОДДЕЛКА", "confidence": 88},
    ])
    assert "Nike" in text and "Подделок: 1" in text and "1999₽" in text


@pytest.mark.asyncio
async def test_discovery_scan_is_tenant_scoped(client, monkeypatch):
    """Regression: findings of a tenant's watch must belong to that tenant
    (checks + listings), not leak into the default tenant."""
    from app.database import (
        create_brand_watch,
        get_watch_listings,
    )

    async def fake_search(marketplace, keyword, limit, browser_page=None):
        return [{"url": "https://www.wildberries.ru/catalog/424242/detail.aspx",
                 "sku": "424242", "title": "T", "price": 1000.0, "seller": "S"}]

    async def fake_fetch(url):
        return {"image_base64": base64.b64encode(_png()).decode(),
                "content_type": "image/png"}

    async def fake_resilient(orig, sus, meta, preferred_provider=None):
        return (
            {"verdict": "ПОДДЕЛКА", "confidence": 90, "summary": "f",
             "risk_level": "high", "indicators": []},
            {"provider": "gemini", "verdict_source": "llm_analysis"},
        )

    async def no_consensus(result, provider, o, s, m):
        return result, {"consensus": "not_needed"}

    monkeypatch.setattr(
        "app.services.discovery.search_parsers.search_marketplace", fake_search)
    monkeypatch.setattr("app.services.browser_service.PLAYWRIGHT_AVAILABLE", False)
    monkeypatch.setattr(
        "app.services.marketplace_image_fetcher.parse_marketplace_image", fake_fetch)
    monkeypatch.setattr(gateway, "analyze_resilient", fake_resilient)
    monkeypatch.setattr(gateway, "run_consensus", no_consensus)

    # Watch owned by tenant #2.
    async def make_watch():
        from app.database import create_brand_watch

        return await create_brand_watch(
            "TenantBrand", "kw", "WB", "0 */6 * * *", 24,
            json.dumps([base64.b64encode(_png((200, 30, 30))).decode()]),
            tenant_id=2,
        )

    wid = await make_watch()

    from app.services.discovery_engine import run_watch_scan

    stats = await run_watch_scan(wid)
    assert stats["analyzed"] == 1

    rows = await get_watch_listings(wid)
    assert rows[0]["tenant_id"] == 2

    # The saved check must also belong to tenant 2 (not default tenant 1).
    import aiosqlite

    from app import database

    async with aiosqlite.connect(database.DB_PATH) as db:
        cur = await db.execute(
            "SELECT tenant_id FROM checks WHERE url LIKE '%424242%'")
        check_tenant = (await cur.fetchone())[0]
    assert check_tenant == 2