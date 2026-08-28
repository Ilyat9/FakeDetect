"""A-C4: MockProvider must give loadtests/locustfile.py a real, no-cost,
no-network path through the app so SLO measurements don't require paid LLM
calls or reach any real provider.
"""

import asyncio
import io

import pytest
from PIL import Image

from app.core.config import get_api_key_for_provider, get_llm_provider, reset_provider_cache, settings
from app.llm_provider import MockProvider, ProviderType, create_provider


def _png() -> bytes:
    img = Image.new("RGB", (16, 16), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_mock_provider_needs_no_real_api_key():
    assert get_api_key_for_provider(ProviderType.MOCK.value)


def test_create_provider_mock_returns_mock_provider():
    provider = create_provider("mock", "unused")
    assert isinstance(provider, MockProvider)


def test_mock_provider_analyze_returns_verdict_without_network():
    provider = MockProvider()
    result = asyncio.run(provider.analyze(_png(), _png(), {"brand": "X"}))
    assert result["verdict"] in ("ОРИГИНАЛ", "ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО")
    assert "confidence" in result


def test_mock_provider_simulated_failure_rate(monkeypatch):
    provider = MockProvider(failure_rate=1.0)
    with pytest.raises(RuntimeError):
        asyncio.run(provider.analyze(_png(), _png(), {}))


def test_get_llm_provider_mock_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, "provider", "mock")
    reset_provider_cache()
    try:
        provider = get_llm_provider("mock")
        assert isinstance(provider, MockProvider)
    finally:
        reset_provider_cache()


def test_analyze_endpoint_works_with_mock_provider(client, monkeypatch):
    monkeypatch.setattr(settings, "provider", "mock")
    reset_provider_cache()
    try:
        res = client.post("/api/v1/analyze", files={
            "original": ("o.png", _png(), "image/png"),
            "suspect": ("s.png", _png(), "image/png"),
        }, data={"brand": "MockLoadTest"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["verdict"] in ("ОРИГИНАЛ", "ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО")
    finally:
        reset_provider_cache()
