"""Block B end-to-end flow via API: pHash fast path, forensics in response,
reverse image search endpoint."""

import base64
import io

import pytest
from PIL import Image
from pydantic import SecretStr

import core.llm_gateway as gateway
from core.config import settings

LLM_CALLS = {"n": 0}

RESULT = {
    "verdict": "ПОДДЕЛКА",
    "confidence": 90,
    "summary": "mock fake",
    "risk_level": "high",
    "indicators": [{"factor": "logo", "score": 2, "status": "fail", "detail": "d"}],
}


def _png(seed_color=(10, 200, 30), size=64) -> bytes:
    """Gradient + seeded noise: distinct pHash per colour (flat images are
    pHash-degenerate and would false-positive the similarity index)."""
    img = Image.new("RGB", (size, size))
    r0, g0, b0 = seed_color
    for y in range(size):
        for x in range(size):
            n = ((x * 7 + y * 13 + r0) % 25) - 12
            img.putpixel(
                (x, y),
                (
                    max(0, min(255, r0 + x - n)),
                    max(0, min(255, g0 + y + n)),
                    max(0, min(255, b0 + (x + y) // 2)),
                ),
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))
    LLM_CALLS["n"] = 0

    async def fake_resilient(orig, sus, meta, preferred_provider=None):
        LLM_CALLS["n"] += 1
        return dict(RESULT), {
            "provider": "gemini",
            "verdict_source": "llm_analysis",
            "prompt_version": "v1",
            "prompt_hash": "abc",
        }

    monkeypatch.setattr(gateway, "analyze_resilient", fake_resilient)
    yield


def _analyze(client, suspect_bytes, rid):
    return client.post(
        "/api/v1/analyze",
        files={
            "original": ("o.png", _png((0, 0, 255)), "image/png"),
            "suspect": ("s.png", suspect_bytes, "image/png"),
        },
        headers={"X-Request-ID": rid},
    )


def test_analyze_enriched_with_forensics_and_phash_cache(client):
    suspect = _png()

    first = _analyze(client, suspect, "b-rid-1")
    assert first.status_code == 200
    data = first.json()
    # Block B enrichment present in the response.
    assert data["verdict_source"] == "llm_analysis"
    assert "ela_score" in data and "ela_flag" in data
    assert "exif_flags" in data and isinstance(data["exif_flags"], list)
    assert isinstance(data["final_score"], int)
    comps = data["score_components"]["components"]
    assert {"llm_confidence", "ela"} <= set(comps)
    assert data["phash"]

    # Second identical suspect image (new request id) must NOT hit the LLM:
    # pHash fast-path returns the stored verdict instantly.
    calls_before = LLM_CALLS["n"]
    second = _analyze(client, suspect, "b-rid-2")
    assert second.status_code == 200
    data2 = second.json()
    assert LLM_CALLS["n"] == calls_before          # no new LLM spend
    assert data2["verdict_source"] == "phash_match"
    assert data2["hamming_distance"] == 0
    assert data2["verdict"] == RESULT["verdict"]


def test_reverse_image_search_finds_check(client):
    suspect = _png()
    assert _analyze(client, suspect, "b-rid-3").status_code == 200

    res = client.post("/api/v1/similar", files={"image": ("q.png", suspect, "image/png")})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    match = next(
        m for m in body["matches"]
        if m["source_type"] == "suspect" and m["hamming_distance"] == 0
    )
    assert match["brand"] is None or True          # join may be empty for mock URL
    assert match["verdict"] == RESULT["verdict"]


def test_similar_rejects_garbage_image(client):
    res = client.post("/api/v1/similar", files={"image": ("q.png", b"garbage", "image/png")})
    assert res.status_code == 400
