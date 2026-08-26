"""Block A tests: resilient gateway (failover, validation, corrective retry)."""

import pytest
from pydantic import SecretStr

import core.llm_gateway as gateway
from core.config import settings

VALID_OUTPUT = {
    "verdict": "ПОДОЗРИТЕЛЬНО",
    "confidence": 55,
    "summary": "ok summary",
    "risk_level": "medium",
    "indicators": [{"factor": "logo", "score": 5, "status": "warn", "detail": "d"}],
    "recommendation": "check manually",
}


class ScriptedProvider:
    """Returns queued outputs in order; raises queued exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def analyze(self, original_bytes, suspect_bytes, meta):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k-gemini"))
    monkeypatch.setattr(settings, "grok_api_key", SecretStr("k-grok"))
    gateway.reset_resilience_state()
    yield
    gateway.reset_resilience_state()


@pytest.mark.asyncio
async def test_failover_to_second_provider(monkeypatch):
    providers = {
        "gemini": ScriptedProvider([ConnectionError("boom")]),
        "grok": ScriptedProvider([dict(VALID_OUTPUT)]),
    }
    monkeypatch.setattr(
        gateway, "get_llm_provider", lambda name: providers[name]
    )
    data, source = await gateway.analyze_resilient(b"a", b"b", {})
    assert data["verdict"] == "ПОДОЗРИТЕЛЬНО"
    assert source["provider"] == "grok"
    assert source["verdict_source"] == "llm_analysis"
    assert source["prompt_version"]  # A.8 fingerprint present


@pytest.mark.asyncio
async def test_corrective_retry_on_invalid_json(monkeypatch):
    provider = ScriptedProvider([
        {"verdict": "мусор", "confidence": 999},   # invalid
        dict(VALID_OUTPUT),                        # corrective retry succeeds
    ])
    monkeypatch.setattr(gateway, "get_llm_provider", lambda name: provider)
    monkeypatch.setattr(settings, "grok_api_key", None)  # single provider path
    data, source = await gateway.analyze_resilient(b"a", b"b", {})
    assert provider.calls == 2
    assert data["verdict"] == "ПОДОЗРИТЕЛЬНО"


@pytest.mark.asyncio
async def test_all_down_raises_queueable_error(monkeypatch):
    providers = {
        "gemini": ScriptedProvider([ConnectionError("x")]),
        "grok": ScriptedProvider([ConnectionError("y")]),
    }
    monkeypatch.setattr(gateway, "get_llm_provider", lambda name: providers[name])
    with pytest.raises(gateway.AllProvidersDownError) as exc:
        await gateway.analyze_resilient(b"a", b"b", {})
    assert len(exc.value.attempts) == 2


@pytest.mark.asyncio
async def test_all_invalid_raises_output_error(monkeypatch):
    bad = {"verdict": "?", "confidence": -5}
    providers = {
        "gemini": ScriptedProvider([bad, bad]),  # + corrective retry
        "grok": ScriptedProvider([bad, bad]),
    }
    monkeypatch.setattr(gateway, "get_llm_provider", lambda name: providers[name])
    with pytest.raises(gateway.AllOutputsInvalidError):
        await gateway.analyze_resilient(b"a", b"b", {})


@pytest.mark.asyncio
async def test_circuit_opens_and_skips_provider(monkeypatch):
    monkeypatch.setattr(settings, "cb_failure_threshold", 2)
    monkeypatch.setattr(settings, "grok_api_key", None)  # single-provider path
    gateway.reset_resilience_state()
    provider = ScriptedProvider([ConnectionError("x")] * 10)
    monkeypatch.setattr(gateway, "get_llm_provider", lambda name: provider)

    # Two failing requests trip the breaker (threshold=2).
    for _ in range(2):
        with pytest.raises(gateway.AllProvidersDownError):
            await gateway.analyze_resilient(b"a", b"b", {})

    # Third request: circuit open — no new call is made.
    calls_before = provider.calls
    with pytest.raises(gateway.AllProvidersDownError) as exc:
        await gateway.analyze_resilient(b"a", b"b", {})
    outcomes = [a["outcome"] for a in exc.value.attempts]
    assert outcomes == ["circuit_open"]
    assert provider.calls == calls_before
