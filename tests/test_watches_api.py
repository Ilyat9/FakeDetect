"""Block C: brand watch CRUD via the HTTP API."""

import base64
import io
import json

import pytest
from PIL import Image
from pydantic import SecretStr

from app.core.config import settings


def _png_bytes() -> bytes:
    img = Image.new("RGB", (32, 32), (90, 90, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(settings, "api_secret_key", None)
    yield


def test_watch_crud_flow(client):
    # CREATE
    res = client.post("/api/v1/watches", data={
        "brand_name": "ApiWatchBrand",
        "keywords": "nike air, nike max",
        "marketplaces": "WB,Ozon",
        "cron_schedule": "0 */3 * * *",
        "digest_interval_hours": 12,
    }, files={"reference": ("ref.png", _png_bytes(), "image/png")})
    assert res.status_code == 201, res.text
    wid = res.json()["id"]

    # LIST (no raw reference payload leaked)
    listing = client.get("/api/v1/watches").json()["watches"]
    entry = next(w for w in listing if w["id"] == wid)
    assert "reference_images" not in entry
    assert entry["brand_name"] == "ApiWatchBrand"
    assert entry["next_run_at"] is not None  # computed at creation time

    # GET detail
    detail = client.get(f"/api/v1/watches/{wid}").json()
    assert detail["keywords"] == "nike air,nike max"

    # Invalid cron rejected with 422
    bad = client.post("/api/v1/watches", data={
        "brand_name": "BadCron", "keywords": "x", "cron_schedule": "whenever",
    }, files={"reference": ("ref.png", _png_bytes(), "image/png")})
    assert bad.status_code == 422

    # Listings of a fresh watch are empty but reachable
    empty = client.get(f"/api/v1/watches/{wid}/listings").json()
    assert empty["total"] == 0

    # DELETE
    assert client.delete(f"/api/v1/watches/{wid}").status_code == 200
    assert client.get(f"/api/v1/watches/{wid}").status_code == 404


def test_run_now_triggers_scan_task(client, monkeypatch):
    res = client.post("/api/v1/watches", data={
        "brand_name": "RunNowBrand", "keywords": "kw",
    }, files={"reference": ("ref.png", _png_bytes(), "image/png")})
    wid = res.json()["id"]

    called = {"n": 0}

    async def fake_scan(watch_id):
        called["n"] += 1
        return {"status": "ok"}

    monkeypatch.setattr("app.services.discovery_engine.run_watch_scan", fake_scan)

    r = client.post(f"/api/v1/watches/{wid}/run-now")
    assert r.status_code == 200
    assert r.json()["status"] == "started"

    # Background task executes in the TestClient loop; give it a moment.
    import time

    for _ in range(20):
        if called["n"]:
            break
        time.sleep(0.05)
    assert called["n"] == 1