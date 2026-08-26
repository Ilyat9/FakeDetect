"""Block F tests: partner REST API and billing webhooks."""

import base64
import hashlib
import hmac
import io
import json
import uuid
from datetime import datetime

import pytest
from PIL import Image
from pydantic import SecretStr

import core.llm_gateway as gateway
from core.config import settings
from tests.test_tenancy import _issue_key, _make_tenant, _png


@pytest.fixture(autouse=True)
def _llm_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))


@pytest.fixture()
def fake_llm(monkeypatch):
    async def fake(orig, sus, meta, preferred_provider=None):
        return (
            {"verdict": "ПОДДЕЛКА", "confidence": 91, "summary": "fake",
             "risk_level": "high", "indicators": []},
            {"provider": "gemini", "verdict_source": "llm_analysis"},
        )

    monkeypatch.setattr(gateway, "analyze_resilient", fake)
    yield


def test_partner_api_auth_and_flow(client, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "partner_rate_limit_per_min", 100)
    key = _issue_key("analyst")

    # No key at all → 401; bogus key → 403.
    files = {
        "original": ("o.png", _png(), "image/png"),
        "suspect": ("s.png", _png((9, 9, 9)), "image/png"),
    }
    assert client.post("/api/v1/partner/checks", files=files).status_code == 401
    assert client.post("/api/v1/partner/checks", files=files,
                       headers={"X-API-Key": "bogus"}).status_code == 403

    r = client.post("/api/v1/partner/checks", files=files,
                    data={"brand": "PartnerBrand"},
                    headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    rid = r.json()["request_id"]

    got = client.get(f"/api/v1/partner/checks/{rid}", headers={"X-API-Key": key})
    assert got.status_code == 200
    assert got.json()["verdict"] == "ПОДДЕЛКА"

    stats = client.get("/api/v1/partner/stats", headers={"X-API-Key": key})
    assert stats.status_code == 200
    assert stats.json()["quota"]["checks_used_this_month"] >= 1


def test_partner_rate_limit_429(client, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "partner_rate_limit_per_min", 2)
    key = _issue_key("admin")  # unique raw key → fresh token bucket

    codes = []
    for _ in range(4):
        r = client.post("/api/v1/partner/checks", files={
            "original": ("o.png", _png(), "image/png"),
            "suspect": ("s.png", _png((5, 5, 5)), "image/png"),
        }, headers={"X-API-Key": key})
        codes.append(r.status_code)
    assert codes.count(429) >= 1


def test_stripe_webhook_updates_plan_and_limits(client, monkeypatch):
    secret = "whsec_test123"
    monkeypatch.setattr(settings, "billing_stripe_webhook_secret",
                        SecretStr(secret))
    tenant_b = _make_tenant("BillingCo")

    def signed(payload: dict) -> tuple:
        body = json.dumps(payload).encode()
        ts = str(int(datetime.now().timestamp()))
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + body,
                       hashlib.sha256).hexdigest()
        return body, {"stripe-signature": f"t={ts},v1={sig}"}, ts

    body, headers, ts = signed({
        "tenant_id": tenant_b, "event": "subscription_activated",
        "plan": "business", "external_sub_id": "sub_123",
    })

    # Wrong signature rejected first.
    bad = client.post("/api/v1/billing/webhook/stripe",
                      content=body,
                      headers={"stripe-signature": f"t={ts},v1=deadbeef"})
    assert bad.status_code == 400

    ok = client.post("/api/v1/billing/webhook/stripe",
                     content=body, headers=headers)
    assert ok.status_code == 200

    import asyncio
    from database import get_tenant

    tenant = asyncio.run(get_tenant(tenant_b))
    assert tenant["plan"] == "business"
    assert tenant["max_checks_per_month"] == 20000
    assert tenant["is_active"] == 1

    # Cancellation deactivates the tenant.
    cancel_payload, cancel_headers, _ts = signed({
        "tenant_id": tenant_b, "event": "subscription_cancelled",
    })
    r = client.post("/api/v1/billing/webhook/stripe",
                    content=cancel_payload, headers=cancel_headers)
    assert r.status_code == 200

    inactive = asyncio.run(get_tenant(tenant_b))
    assert inactive["is_active"] == 0