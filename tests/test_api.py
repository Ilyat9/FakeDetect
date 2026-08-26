"""API integration tests via FastAPI TestClient."""

import asyncio
import io

import pandas as pd
import pytest
from fastapi import UploadFile
from pydantic import SecretStr


def _xlsx_bytes(rows: list) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


def test_health(client):
    """Block A.5: /health reports detailed per-dependency status."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ok", "degraded")
    assert data["provider"] == "gemini"
    checks = data["checks"]
    assert checks["database"]["ok"] is True
    for name in ("gemini", "grok"):
        assert name in checks["llm_providers"]
        assert "configured" in checks["llm_providers"][name]
        assert "circuit_state" in checks["llm_providers"][name] \
            if checks["llm_providers"][name]["configured"] else True
    assert "available" in checks["playwright"]
    # Deep mode pings provider REST endpoints.
    res_deep = client.get("/health?deep=true")
    assert res_deep.status_code == 200


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "FakeDetect" in res.text or "<html" in res.text.lower()


def test_api_v1_history_pagination_shape(client):
    res = client.get("/api/v1/history?limit=5&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert {"checks", "total", "limit", "offset"} <= set(data.keys())
    assert data["limit"] == 5


def test_legacy_paths_still_work(client):
    """Grace period: unversioned paths must keep working."""
    assert client.get("/history").status_code == 200
    assert client.get("/stats").status_code == 200


def test_whitelist_crud_via_v1(client):
    res = client.post("/api/v1/whitelist", data={
        "brand": "TestBrandAPI", "seller_name": "ApiSeller", "marketplace": "WB",
    })
    assert res.status_code == 200
    entry_id = res.json()["id"]

    res = client.get("/api/v1/whitelist", params={"brand": "TestBrandAPI"})
    assert any(e["seller_name"] == "ApiSeller" for e in res.json()["entries"])

    assert client.delete(f"/api/v1/whitelist/{entry_id}").status_code == 200


def test_protected_endpoints_require_api_key(client, monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "api_secret_key", SecretStr("topsecret"))

    for path in ("/api/v1/stats", "/api/v1/history"):
        assert client.get(path).status_code == 401
        ok = client.get(path, headers={"X-API-Key": "topsecret"})
        assert ok.status_code == 200

    # Whitelist write is protected too
    res = client.post("/api/v1/whitelist", data={"brand": "b", "seller_name": "s"})
    assert res.status_code == 401


def test_parse_image_ssrf_blocked(client):
    res = client.post("/api/v1/parse-image", data={"url": "http://169.254.169.254/latest/meta-data/.jpg"})
    assert res.status_code in (400, 404)


def test_analyze_without_api_key(client):
    files = {
        "original": ("o.png", b"\x89PNG fake", "image/png"),
        "suspect": ("s.png", b"\x89PNG fake", "image/png"),
    }
    res = client.post("/api/v1/analyze", files=files)
    assert res.status_code == 500
    assert res.json()["detail"] == "API key not configured"


def test_batch_rejects_invalid_provider(client):
    files = {
        "file": ("data.xlsx", _xlsx_bytes([{"url": "https://wildberries.ru/x"}]), "application/octet-stream"),
        "reference": ("ref.png", b"\x89PNG fake", "image/png"),
    }
    res = client.post("/api/v1/batch", files=files,
                      data={"provider_name": "notaprovider"})
    assert res.status_code == 422


def test_batch_requires_url_column(client):
    files = {
        "file": ("data.xlsx", _xlsx_bytes([{"foo": 1}]), "application/octet-stream"),
        "reference": ("ref.png", b"\x89PNG fake", "image/png"),
    }
    res = client.post("/api/v1/batch", files=files)
    assert res.status_code == 400


def test_full_batch_flow_with_mocked_llm(client, monkeypatch, tmp_path):
    """Regression test for fix 1.1: batch must complete and produce an xlsx report."""
    import batch_processor as bp

    class FakeProvider:
        async def analyze(self, original_bytes, suspect_bytes, meta):
            return {
                "verdict": "ПОДОЗРИТЕЛЬНО", "confidence": 55,
                "summary": "mock result", "risk_level": "medium",
                "indicators": [{"factor": "f", "score": 5, "status": "warn", "detail": "d"}],
            }

    async def fake_fetch_suspect(self, url):
        return b"\x89PNG fake-suspect"

    from core.config import settings
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("test-key"))
    monkeypatch.setattr(bp, "create_provider", lambda name, key: FakeProvider())
    monkeypatch.setattr(bp.BatchProcessor, "_fetch_suspect_image", fake_fetch_suspect)

    rows = [
        {"url": "https://www.wildberries.ru/catalog/111/detail.aspx", "brand": "Nike"},
        {"url": "https://www.ozon.ru/product/p-222/", "brand": "Nike"},
    ]
    files = {
        "file": ("data.xlsx", _xlsx_bytes(rows), "application/octet-stream"),
        "reference": ("ref.png", b"\x89PNG fake-reference", "image/png"),
    }
    res = client.post("/api/v1/batch", files=files, data={"provider_name": "gemini"})
    assert res.status_code == 200
    task_id = res.json()["task_id"]

    # The endpoint spawns the background worker via asyncio.create_task;
    # poll status like the frontend does until it completes.
    import time
    task = {"status": "processing"}
    for _ in range(100):
        time.sleep(0.05)
        task = client.get(f"/api/v1/batch/{task_id}").json()
        if task["status"] in ("completed", "error"):
            break

    assert task["status"] == "completed", task
    assert task["done"] == 2

    download = client.get(f"/api/v1/batch/{task_id}/download")
    assert download.status_code == 200
    assert (download.headers["content-type"]
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    report = pd.read_excel(io.BytesIO(download.content))
    assert len(report) == 2
    assert "verdict" in report.columns
    assert list(report["verdict"]) == ["ПОДОЗРИТЕЛЬНО", "ПОДОЗРИТЕЛЬНО"]
