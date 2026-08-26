"""Block C e2e: full discovery scan cycle with mocked search + LLM."""

import base64
import io
import json

import pytest
from PIL import Image
from pydantic import SecretStr

import core.llm_gateway as gateway
from core.config import settings


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
    from database import (
        create_brand_watch,
        get_recent_findings,
        get_watch_listings,
    )

    settings.gemini_api_key = SecretStr("k")

    listings = [
        {"url": "https://www.wildberries.ru/catalog/777/detail.aspx",
         "sku": "777", "title": "Fake Watch", "price": 1500.0, "seller": "ScamCo"},
        {"url": "https://www.wildberries.ru/catalog/888/detail.aspx",
         "sku": "888", "title": "Original Watch", "price": 30000.0, "seller": "AuthStore"},
    ]

    async def fake_search(marketplace, keyword, limit, browser_page=None):
        return [dict(l) for l in listings]

    monkeypatch.setattr(
        "services.discovery.search_parsers.search_marketplace", fake_search
    )
    monkeypatch.setattr("services.browser_service.PLAYWRIGHT_AVAILABLE", False)

    async def fake_fetch(url):
        # Distinct image per URL: identical photos would legitimately collapse
        # into the B.1 pHash fast path and skip the LLM for the 2nd listing.
        seed = sum(ord(ch) for ch in url)
        img_bytes = _png((seed % 256, (seed * 7) % 256, (seed * 13) % 256))
        return {"image_base64": base64.b64encode(img_bytes).decode(),
                "content_type": "image/png"}

    monkeypatch.setattr(
        "services.marketplace_image_fetcher.parse_marketplace_image", fake_fetch
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
    monkeypatch.setattr("telegram_alerts.send_telegram_alert", fake_alert)

    wid = await create_brand_watch(
        "WatchBrand", "watch kw", "WB", "0 */6 * * *", 24,
        json.dumps([base64.b64encode(_png((200, 30, 30))).decode()]),
    )

    from services.discovery_engine import run_watch_scan

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
    from services.discovery_engine import build_digest_text

    text = build_digest_text("Nike", [
        {"url": "https://x/1", "title": "t", "price": 1999.0, "seller": "S",
         "verdict": "ПОДДЕЛКА", "confidence": 88},
    ])
    assert "Nike" in text and "Подделок: 1" in text and "1999₽" in text