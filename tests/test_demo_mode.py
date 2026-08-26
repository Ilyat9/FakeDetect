"""Public demo deployment tests (DEMO_MODE): anonymous analyst role,
per-IP rate limits, /metrics gating, hard cost cap."""

import base64
import io
import uuid

import pytest
from PIL import Image

from core.config import settings


def _png(color=(10, 20, 30)) -> bytes:
    img = Image.new("RGB", (64, 64))
    c0, c1, c2 = color
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), ((c0 + x) % 256, (c1 + y) % 256, (c2 + x + y) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def demo_env(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    from services import tenancy

    tenancy._ip_buckets.clear()
    yield
    tenancy._ip_buckets.clear()


def test_demo_anonymous_can_analyze(demo_env, client, monkeypatch):
    """Anonymous visitor acts as analyst of the Default tenant."""
    import core.llm_gateway as gateway
    from pydantic import SecretStr

    async def fake(orig, sus, meta, preferred_provider=None):
        return (
            {"verdict": "ПОДДЕЛКА", "confidence": 90, "summary": "f",
             "risk_level": "high", "indicators": []},
            {"provider": "gemini", "verdict_source": "llm_analysis"},
        )

    monkeypatch.setattr(gateway, "analyze_resilient", fake)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))

    r = client.post("/api/v1/analyze", files={
        "original": ("o.png", _png((0, 0, 0)), "image/png"),
        "suspect": ("s.png", _png(), "image/png"),
    })
    assert r.status_code == 200
    # Reads are also allowed (viewer <= analyst).
    assert client.get("/api/v1/history").status_code == 200


def test_demo_metrics_hidden_from_anonymous(demo_env, client):
    """/metrics must not leak internals to anonymous demo visitors."""
    assert client.get("/metrics").status_code == 404


def test_demo_per_ip_analyze_rate_limit(demo_env, client, monkeypatch):
    """Expensive endpoint is throttled per IP even for anonymous visitors."""
    import core.llm_gateway as gateway
    from pydantic import SecretStr

    async def fake(orig, sus, meta, preferred_provider=None):
        return (
            {"verdict": "ОРИГИНАЛ", "confidence": 95, "summary": "ok",
             "risk_level": "low", "indicators": []},
            {"provider": "gemini", "verdict_source": "llm_analysis"},
        )

    monkeypatch.setattr(gateway, "analyze_resilient", fake)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))
    monkeypatch.setattr(settings, "ip_rate_limit_analyze_per_min", 2)

    codes = []
    for _ in range(4):
        r = client.post("/api/v1/analyze", files={
            "original": ("o.png", _png((0, 0, 0)), "image/png"),
            "suspect": ("s.png", _png(
                (uuid.uuid4().int % 200, 50, 90)), "image/png"),
        }, headers={"X-Forwarded-For": "203.0.113.7"})
        codes.append(r.status_code)
    assert codes[:2] == [200, 200]
    assert 429 in codes


def test_demo_cost_cap_applied_at_bootstrap(demo_env, client):
    """Bootstrap caps the shared demo tenant's monthly budget."""
    import asyncio

    from database import get_tenant

    tenant = asyncio.run(get_tenant(1))
    assert int(tenant["max_checks_per_month"]) <= settings.demo_max_checks_per_month