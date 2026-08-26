"""Block B.3 tests: multi-model consensus rules."""

import pytest
from pydantic import SecretStr

import core.llm_gateway as gateway
from core.config import settings

BASE = {
    "verdict": "ПОДОЗРИТЕЛЬНО",
    "confidence": 55,
    "summary": "borderline",
    "risk_level": "medium",
    "indicators": [],
}


class FixedProvider:
    def __init__(self, verdict, confidence):
        self.verdict, self.confidence = verdict, confidence

    async def analyze(self, original_bytes, suspect_bytes, meta):
        return {
            "verdict": self.verdict, "confidence": self.confidence,
            "summary": f"{self.verdict}", "risk_level": "low", "indicators": [],
        }


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k1"))
    monkeypatch.setattr(settings, "grok_api_key", SecretStr("k2"))
    gateway.reset_resilience_state()
    yield
    gateway.reset_resilience_state()


def _wire(monkeypatch, providers: dict):
    monkeypatch.setattr(gateway, "get_llm_provider", lambda name: providers[name])


@pytest.mark.asyncio
async def test_consensus_agreement_boosts_confidence(monkeypatch):
    _wire(monkeypatch, {
        "grok": FixedProvider("ПОДОЗРИТЕЛЬНО", 65),
    })
    first = dict(BASE)  # confidence 55 → inside band 40..70
    result, meta = await gateway.run_consensus(
        first, "gemini", b"a", b"b", {}
    )
    assert meta["consensus"] == "agreement"
    assert result["confidence"] == min(99, (55 + 65) // 2 + 10)   # 70
    assert len(result["raw_model_responses"]) == 2


@pytest.mark.asyncio
async def test_consensus_disagreement_escalates_to_manual_review(monkeypatch):
    _wire(monkeypatch, {
        "grok": FixedProvider("ОРИГИНАЛ", 60),
    })
    first = dict(BASE)
    result, meta = await gateway.run_consensus(first, "gemini", b"a", b"b", {})
    assert meta["consensus"] == "disagreement"
    assert result["verdict"] == "ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ"
    assert result["confidence"] == (55 + 60) // 2
    assert [r["provider"] for r in result["raw_model_responses"]] == ["gemini", "grok"]
    assert "разошлись" in result["summary"]


@pytest.mark.asyncio
async def test_consensus_skipped_outside_band(monkeypatch):
    called = {"n": 0}

    class Spy(FixedProvider):
        async def analyze(self, *a, **kw):
            called["n"] += 1
            return await super().analyze(*a, **kw)

    _wire(monkeypatch, {"grok": Spy("ОРИГИНАЛ", 90)})
    first = {**BASE, "confidence": 85}     # outside 40..70
    result, meta = await gateway.run_consensus(first, "gemini", b"a", b"b", {})
    assert meta["consensus"] == "not_needed"
    assert result["verdict"] == "ПОДОЗРИТЕЛЬНО"
    assert called["n"] == 0
    assert "raw_model_responses" not in result


@pytest.mark.asyncio
async def test_consensus_second_provider_down_keeps_first(monkeypatch):
    class DownProvider:
        async def analyze(self, *a, **kw):
            raise ConnectionError("down")

    _wire(monkeypatch, {"grok": DownProvider()})
    first = dict(BASE)
    result, meta = await gateway.run_consensus(first, "gemini", b"a", b"b", {})
    assert meta["consensus"] == "second_opinion_unavailable"
    assert result["verdict"] == "ПОДОЗРИТЕЛЬНО"
    # Raw first answer is still preserved for audit.
    assert result["raw_model_responses"][0]["provider"] == "gemini"


@pytest.mark.asyncio
async def test_consensus_no_other_configured_provider(monkeypatch):
    monkeypatch.setattr(settings, "grok_api_key", None)
    first = dict(BASE)
    result, meta = await gateway.run_consensus(first, "gemini", b"a", b"b", {})
    assert meta["consensus"] == "second_opinion_unavailable"
