"""Block A tests: idempotency (A.2) and retry queue (A.6) end-to-end via API."""

import base64

import pytest
from pydantic import SecretStr

import core.llm_gateway as gateway
from core.config import settings

RESULT = {
    "verdict": "ОРИГИНАЛ",
    "confidence": 90,
    "summary": "mock",
    "risk_level": "low",
    "indicators": [],
}


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))
    yield


def _files():
    img = base64.b64encode(b"fake-image").decode()
    return {
        "original": ("o.png", b"x", "image/png"),
        "suspect": ("s.png", b"y", "image/png"),
    }


def test_idempotent_analyze_replays_cached_result(client, monkeypatch):
    calls = {"n": 0}

    async def fake_resilient(orig, sus, meta, preferred_provider=None):
        calls["n"] += 1
        return dict(RESULT), {
            "provider": "gemini",
            "verdict_source": "llm_analysis",
            "prompt_version": "v1",
            "prompt_hash": "abc",
        }

    monkeypatch.setattr(gateway, "analyze_resilient", fake_resilient)

    headers = {"X-Request-ID": "test-req-id-1"}
    first = client.post("/api/v1/analyze", files=_files(), headers=headers)
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert first.headers["X-Request-ID"] == "test-req-id-1"

    second = client.post("/api/v1/analyze", files=_files(), headers=headers)
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    # The LLM was called exactly once — no double spend on retry.
    assert calls["n"] == 1
    assert second.json()["verdict"] == "ОРИГИНАЛ"


def test_all_providers_down_returns_202_and_pollable(client, monkeypatch):
    async def down(orig, sus, meta, preferred_provider=None):
        raise gateway.AllProvidersDownError("all down", [{"provider": "gemini", "outcome": "error"}])

    monkeypatch.setattr(gateway, "analyze_resilient", down)

    res = client.post(
        "/api/v1/analyze",
        files=_files(),
        headers={"X-Request-ID": "queued-req-1"},
    )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "queued"
    assert body["poll_url"].endswith("/queue/queued-req-1")
    assert body["estimated_wait_seconds"] > 0

    status = client.get("/api/v1/queue/queued-req-1")
    assert status.status_code == 200
    assert status.json()["status"] == "pending"


def test_queue_unknown_request_404(client):
    assert client.get("/api/v1/queue/no-such-id").status_code == 404


@pytest.mark.asyncio
async def test_retry_worker_processes_pending_item(client, monkeypatch):
    from database import cache_get_result, enqueue_retry
    from services.retry_worker import process_pending_once

    async def ok(orig, sus, meta, preferred_provider=None):
        return dict(RESULT), {}

    monkeypatch.setattr(gateway, "analyze_resilient", ok)

    await enqueue_retry("worker-test-1", {
        "original_b64": base64.b64encode(b"a").decode(),
        "suspect_b64": base64.b64encode(b"b").decode(),
        "meta": {},
    })

    processed = await process_pending_once()
    assert processed >= 1

    cached = await cache_get_result("worker-test-1")
    assert cached is not None
    assert cached["verdict"] == "ОРИГИНАЛ"

    item_status = client.get("/api/v1/queue/worker-test-1").json()
    assert item_status["status"] == "done"
