"""Block F tests: multi-tenancy isolation, roles, quotas."""

import base64
import io
import uuid

import pytest
from PIL import Image
from pydantic import SecretStr

from app.core import llm_gateway as gateway
from app.core.config import settings


def _png(color=(30, 60, 90)) -> bytes:
    img = Image.new("RGB", (64, 64))
    c0, c1, c2 = color
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), ((c0 + x) % 256, (c1 + y) % 256, (c2 + x + y) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _issue_key(role="analyst", tenant_id=1) -> str:
    """Issue a raw API key for a tenant (stored hashed)."""
    import asyncio

    from app.database import create_api_key
    from app.services.tenancy import hash_key

    raw = f"fdtest-{role}-{tenant_id}-{uuid.uuid4().hex[:8]}"

    async def go():
        return await create_api_key(
            tenant_id, hash_key(raw), f"{role}-key", role
        )

    inserted = asyncio.run(go())
    assert inserted == 1
    return raw


def _make_tenant(name, **limits) -> int:
    import asyncio

    import aiosqlite

    from app.database import DB_PATH

    async def go():
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO tenants (name, plan, max_checks_per_month,
                       max_watches, max_users)
                   VALUES (?, 'pro', ?, ?, ?)""",
                (name,
                 limits.get("max_checks_per_month", 100),
                 limits.get("max_watches", 2),
                 limits.get("max_users", 3)),
            )
            await db.commit()
            row = await db.execute("SELECT last_insert_rowid()")
            return (await row.fetchone())[0]

    return asyncio.run(go())


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


@pytest.fixture(autouse=True)
def _llm_key(monkeypatch):
    # /analyze checks provider key presence before running the (mocked) engine.
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))


def _analyze(client, headers, color=(100, 100, 200)):
    return client.post("/api/v1/analyze", files={
        "original": ("o.png", _png((0, 0, 0)), "image/png"),
        "suspect": ("s.png", _png(color), "image/png"),
    }, data={"brand": f"Brand-{color[0]}"}, headers=headers)


# --- isolation ----------------------------------------------------------------------


def test_two_tenants_isolated(client, fake_llm):
    key_a = _issue_key("analyst", tenant_id=1)
    tenant_b = _make_tenant("IsolatedCo")
    key_b = _issue_key("analyst", tenant_id=tenant_b)

    assert _analyze(client, {"X-API-Key": key_a}).status_code == 200
    assert _analyze(client, {"X-API-Key": key_b}, color=(150, 20, 20)).status_code == 200

    hist_b = client.get("/api/v1/history",
                        headers={"X-API-Key": key_b}).json()
    assert hist_b["total"] >= 1
    assert all(c["tenant_id"] == tenant_b for c in hist_b["checks"])
    brands_b = {c["brand"] for c in hist_b["checks"]}
    assert "Brand-100" not in brands_b          # tenant A's check is invisible

    hist_a = client.get("/api/v1/history",
                        headers={"X-API-Key": key_a}).json()
    assert "Brand-150" not in {c["brand"] for c in hist_a["checks"]}


def test_invalid_api_key_rejected(client, fake_llm):
    r = _analyze(client, {"X-API-Key": "bogus-key"})
    assert r.status_code == 403


# --- roles --------------------------------------------------------------------------


def test_role_gates(client, fake_llm):
    viewer = _issue_key("viewer")
    legal = _issue_key("legal")
    analyst = _issue_key("analyst")

    # Viewer reads but cannot run analyses.
    assert client.get("/api/v1/history",
                      headers={"X-API-Key": viewer}).status_code == 200
    assert _analyze(client, {"X-API-Key": viewer}).status_code == 403

    # Analyst runs an analysis → case auto-created (ПОДДЕЛКА).
    r = _analyze(client, {"X-API-Key": analyst})
    assert r.status_code == 200
    cid = client.get("/api/v1/cases",
                     params={"brand": "Brand-100"},
                     headers={"X-API-Key": analyst}).json()["cases"][0]["id"]

    # Legal reads case + evidence pack...
    assert client.get(f"/api/v1/cases/{cid}",
                      headers={"X-API-Key": legal}).status_code == 200
    pdf = client.get(f"/api/v1/cases/{cid}/evidence-pdf",
                     headers={"X-API-Key": legal})
    assert pdf.status_code == 200

    # ...but may NOT transition statuses or run analyses.
    tr = client.post(f"/api/v1/cases/{cid}/transition",
                     json={"to_status": "UNDER_REVIEW"},
                     headers={"X-API-Key": legal})
    assert tr.status_code == 403
    assert _analyze(client, {"X-API-Key": legal}).status_code == 403


# --- quotas -------------------------------------------------------------------------


def test_quota_exceeded_returns_402_with_details(client, fake_llm):
    tiny = _make_tenant("TinyCo", max_checks_per_month=0)
    key = _issue_key("analyst", tenant_id=tiny)

    r = _analyze(client, {"X-API-Key": key})
    assert r.status_code == 402
    body = r.json()["detail"]
    assert body["error"] == "plan_limit_exceeded"
    assert body["limit"] == "checks_per_month"
    assert body["max"] == 0
    assert "upgrade_hint" in body


# --- batch task isolation (IDOR regression) -----------------------------------------


def test_batch_task_isolated_per_tenant(client):
    """GET /batch/{id} must 404 for a foreign tenant (uuid4 ids are not authz)."""
    import asyncio

    from app.database import create_batch_task

    tenant_a = _make_tenant("BatchCo-A")
    tenant_b = _make_tenant("BatchCo-B")
    key_a = _issue_key("analyst", tenant_id=tenant_a)
    key_b = _issue_key("analyst", tenant_id=tenant_b)

    asyncio.run(create_batch_task("task-owned-by-a", 3, tenant_id=tenant_a))

    # Owner of the task sees it.
    r_ok = client.get("/api/v1/batch/task-owned-by-a", headers={"X-API-Key": key_a})
    assert r_ok.status_code == 200
    assert r_ok.json()["task_id"] == "task-owned-by-a"

    # Foreign tenant gets 404 on both status and download (no existence leak).
    assert client.get("/api/v1/batch/task-owned-by-a",
                      headers={"X-API-Key": key_b}).status_code == 404
    assert client.get("/api/v1/batch/task-owned-by-a/download",
                      headers={"X-API-Key": key_b}).status_code == 404

    # Open-mode / Default-tenant request must not see it either.
    assert client.get("/api/v1/batch/task-owned-by-a").status_code == 404
