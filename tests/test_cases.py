"""Block D tests: case workflow (auto-create, transitions, bulk, SLA)."""

import base64
import io

import pytest
from PIL import Image
from pydantic import SecretStr

import core.llm_gateway as gateway
from core.config import settings

import uuid

FAKE_RESULT = {
    "verdict": "ПОДДЕЛКА",
    "confidence": 90,
    "summary": "clear fake",
    "risk_level": "high",
    "indicators": [{"factor": "logo", "score": 2, "status": "fail", "detail": "d"}],
}


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
def fake_llm(monkeypatch, tmp_path):
    async def fake_resilient(orig, sus, meta, preferred_provider=None):
        return dict(FAKE_RESULT), {
            "provider": "gemini", "verdict_source": "llm_analysis",
            "prompt_version": "v1", "prompt_hash": "h",
        }

    async def no_consensus(result, provider, o, s, m):
        return result, {"consensus": "second_opinion_unavailable"}

    monkeypatch.setattr(gateway, "analyze_resilient", fake_resilient)
    monkeypatch.setattr(gateway, "run_consensus", no_consensus)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "evidence"))
    yield


def _make_check(client) -> tuple:
    """Create a fresh check — unique request id and brand (the session DB is
    shared between tests, so idempotency must not swallow earlier runs'
    requests and background workers must not confuse cases)."""
    tag = uuid.uuid4().hex[:8]
    rid = uuid.uuid4().hex
    res = client.post("/api/v1/analyze", files={
        "original": ("o.png", _png((0, 0, 255)), "image/png"),
        "suspect": ("s.png", _png((200, 50, 50)), "image/png"),
    }, data={"url": f"https://www.wildberries.ru/catalog/{tag}/detail.aspx",
             "brand": f"CaseBrand-{tag}", "seller": "BadSeller"},
        headers={"X-Request-ID": rid})
    assert res.status_code == 200, res.text
    return tag, rid


def _first_case(client, brand) -> dict:
    cases = client.get("/api/v1/cases", params={"brand": brand}).json()["cases"]
    assert cases, f"no case found for brand {brand}"
    return cases[0]


def test_case_auto_created_with_evidence_manifest(client, fake_llm):
    tag, _rid = _make_check(client)
    case = _first_case(client, f"CaseBrand-{tag}")

    assert case["status"] == "DETECTED"
    assert case["seller"] == "BadSeller"

    from services.evidence_store import get_manifest

    manifest = get_manifest(case["check_id"])
    names = {f["name"] for f in manifest}
    assert {"meta.json", "reference.png", "suspect.png"} <= names
    for f in manifest:
        if f["name"] != "meta.json":
            assert len(f["sha256"]) == 64


def test_status_machine_valid_chain_and_terminal_lock(client, fake_llm):
    tag, _rid = _make_check(client)
    cid = _first_case(client, f"CaseBrand-{tag}")["id"]

    chain = ["UNDER_REVIEW", "CONFIRMED_FAKE", "COMPLAINT_FILED",
             "LISTING_REMOVED", "CLOSED"]
    for status in chain:
        r = client.post(f"/api/v1/cases/{cid}/transition", json={
            "to_status": status, "changed_by": "tester", "comment": f"→{status}",
        })
        assert r.status_code == 200, (status, r.text)

    detail = client.get(f"/api/v1/cases/{cid}").json()
    assert detail["case"]["status"] == "CLOSED"
    statuses = [h["to_status"] for h in detail["history"]]
    assert statuses[0] == "DETECTED" and statuses[-1] == "CLOSED"
    # SLA cleared on the terminal status.
    assert detail["case"]["sla_deadline"] is None

    dead = client.post(f"/api/v1/cases/{cid}/transition",
                       json={"to_status": "UNDER_REVIEW"})
    assert dead.status_code == 400


def test_invalid_transition_rejected_with_explanation(client, fake_llm):
    tag, _rid = _make_check(client)
    cid = _first_case(client, f"CaseBrand-{tag}")["id"]

    r = client.post(f"/api/v1/cases/{cid}/transition",
                    json={"to_status": "LISTING_REMOVED"})
    assert r.status_code == 400
    assert "not allowed" in r.json()["detail"]


def test_comments_and_assignee(client, fake_llm):
    tag, _rid = _make_check(client)
    cid = _first_case(client, f"CaseBrand-{tag}")["id"]

    r = client.post(f"/api/v1/cases/{cid}/comments",
                    json={"author": "anna", "text": "Продавец повторно выставил карточку"})
    assert r.status_code == 200

    a = client.post(f"/api/v1/cases/{cid}/assign", json={"assignee": "anna"})
    assert a.status_code == 200

    detail = client.get(f"/api/v1/cases/{cid}").json()
    assert detail["case"]["assignee"] == "anna"
    assert detail["comments"][0]["text"].startswith("Продавец")


def test_bulk_transition(client, fake_llm):
    tag, _rid = _make_check(client)
    # Bulk within OUR brand only: open cases are eligible.
    cases = client.get("/api/v1/cases",
                       params={"brand": f"CaseBrand-{tag}"}).json()["cases"]
    ids = [c["id"] for c in cases if c["status"] != "CLOSED"]
    assert ids

    r = client.post("/api/v1/cases/bulk-transition", json={
        "case_ids": ids, "to_status": "UNDER_REVIEW", "changed_by": "boss",
    })
    body = r.json()
    assert body["transitioned"] == len(ids)
    assert body["failed"] == []


def test_bulk_reports_invalid_targets(client, fake_llm):
    tag, _rid = _make_check(client)
    cid = _first_case(client, f"CaseBrand-{tag}")["id"]
    # DETECTED → LISTING_REMOVED is invalid; bulk must report it, not crash.
    r = client.post("/api/v1/cases/bulk-transition", json={
        "case_ids": [cid], "to_status": "LISTING_REMOVED"})
    body = r.json()
    assert body["transitioned"] == 0
    assert body["failed"][0]["error"]