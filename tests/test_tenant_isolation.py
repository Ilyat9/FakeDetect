"""F-C1 regression suite: tenant A must never be able to reach tenant B's
data through a get-by-id endpoint, even with a guessed/known id.

This is the single source of truth for tenant-isolation regressions. When you
add a new tenant-scoped get-by-id endpoint, add it to RESOURCES below (or to
its own test if the setup doesn't fit the table) — see the checklist in
docs/ARCHITECTURE.md ("Adding a new tenant-scoped endpoint").

Every check here asserts 404 specifically (never 200, never 403): a 403 would
tell tenant B the id exists for someone else, which is itself a leak.
"""

import asyncio
import io
import uuid

import pytest
from PIL import Image
from pydantic import SecretStr

from app import database
from app.core import llm_gateway as gateway
from app.core.config import settings
from app.database import create_api_key, create_batch_task
from app.services.tenancy import hash_key


def _png(color=(40, 80, 120)) -> bytes:
    img = Image.new("RGB", (48, 48), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_tenant(name: str) -> int:
    async def go():
        import aiosqlite

        async with aiosqlite.connect(database.DB_PATH) as db:
            cur = await db.execute(
                """INSERT INTO tenants (name, plan, max_checks_per_month,
                       max_watches, max_users)
                   VALUES (?, 'pro', 1000, 50, 10)""",
                (name,),
            )
            await db.commit()
            row = await db.execute("SELECT last_insert_rowid()")
            return (await row.fetchone())[0]

    return asyncio.run(go())


def _issue_key(tenant_id: int, role: str = "admin") -> str:
    raw = f"fdtest-{role}-{tenant_id}-{uuid.uuid4().hex[:8]}"
    inserted = asyncio.run(
        create_api_key(tenant_id, hash_key(raw), f"{role}-key", role)
    )
    assert inserted == 1
    return raw


@pytest.fixture()
def two_tenants():
    """(tenant_a, key_a, tenant_b, key_b) — two isolated tenants + admin keys."""
    tenant_a = _make_tenant(f"TenantA-{uuid.uuid4().hex[:6]}")
    tenant_b = _make_tenant(f"TenantB-{uuid.uuid4().hex[:6]}")
    return tenant_a, _issue_key(tenant_a), tenant_b, _issue_key(tenant_b)


@pytest.fixture()
def fake_llm(monkeypatch):
    async def fake(orig, sus, meta, preferred_provider=None):
        return (
            {"verdict": "ПОДДЕЛКА", "confidence": 92, "summary": "fake",
             "risk_level": "high", "indicators": []},
            {"provider": "gemini", "verdict_source": "llm_analysis"},
        )

    async def no_consensus(result, provider, o, s, m):
        return result, {"consensus": "second_opinion_unavailable"}

    monkeypatch.setattr(gateway, "analyze_resilient", fake)
    monkeypatch.setattr(gateway, "run_consensus", no_consensus)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))


def _headers(key: str) -> dict:
    return {"X-API-Key": key}


# --- per-resource setup: returns (resource_id, owner_key) --------------------------


def _setup_case(client, owner_key: str, fake_llm) -> str:
    tag = uuid.uuid4().hex[:8]
    res = client.post(
        "/api/v1/analyze",
        files={
            "original": ("o.png", _png((0, 0, 255)), "image/png"),
            "suspect": ("s.png", _png((tag_to_color(tag))), "image/png"),
        },
        data={
            "url": f"https://www.wildberries.ru/catalog/{tag}/detail.aspx",
            "brand": f"IsoBrand-{tag}",
            "seller": "IsoSeller",
        },
        headers=_headers(owner_key),
    )
    assert res.status_code == 200, res.text
    cases = client.get(
        "/api/v1/cases", params={"brand": f"IsoBrand-{tag}"}, headers=_headers(owner_key)
    ).json()["cases"]
    assert cases, "case should have auto-opened for a ПОДДЕЛКА verdict"
    return str(cases[0]["id"])


def tag_to_color(tag: str) -> tuple:
    seed = int(tag[:4], 16)
    return (seed % 256, (seed * 3) % 256, (seed * 7) % 256)


def _setup_batch_task(client, owner_key: str, owner_tenant_id: int) -> str:
    task_id = f"iso-task-{uuid.uuid4().hex[:8]}"
    asyncio.run(create_batch_task(task_id, total=2, tenant_id=owner_tenant_id))
    return task_id


def _setup_watch(client, owner_key: str) -> str:
    res = client.post(
        "/api/v1/watches",
        data={
            "brand_name": f"IsoWatch-{uuid.uuid4().hex[:6]}",
            "keywords": "kw1, kw2",
            "marketplaces": "WB",
            "cron_schedule": "0 7 * * *",
            "digest_interval_hours": 24,
        },
        files={"reference": ("ref.png", _png(), "image/png")},
        headers=_headers(owner_key),
    )
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


RESOURCE_ENDPOINTS = {
    "case": [
        "/api/v1/cases/{id}",
        "/api/v1/cases/{id}/history",
        "/api/v1/cases/{id}/comments",
        "/api/v1/cases/{id}/evidence-pdf",
        "/api/v1/cases/{id}/complaint",
    ],
    "batch_task": [
        "/api/v1/batch/{id}",
        "/api/v1/batch/{id}/download",
    ],
    "brand_watch": [
        "/api/v1/watches/{id}",
        "/api/v1/watches/{id}/listings",
    ],
}


@pytest.mark.parametrize("resource", ["case", "batch_task", "brand_watch"])
def test_foreign_tenant_gets_404_on_every_get_endpoint(
    client, two_tenants, fake_llm, resource
):
    tenant_a, key_a, tenant_b, key_b = two_tenants

    if resource == "case":
        resource_id = _setup_case(client, key_a, fake_llm)
    elif resource == "batch_task":
        resource_id = _setup_batch_task(client, key_a, tenant_a)
    elif resource == "brand_watch":
        resource_id = _setup_watch(client, key_a)
    else:  # pragma: no cover
        raise AssertionError(resource)

    for template in RESOURCE_ENDPOINTS[resource]:
        url = template.format(id=resource_id)

        owner_resp = client.get(url, headers=_headers(key_a))
        assert owner_resp.status_code in (200, 404, 400), (
            f"owner request to {url} unexpectedly failed: {owner_resp.status_code} "
            f"{owner_resp.text}"
        )
        # (some endpoints 404 for the owner too if the resource has no data
        # for that sub-path yet, e.g. an empty comments list still returns 200
        # — the meaningful assertion is the foreign-tenant one below)

        foreign_resp = client.get(url, headers=_headers(key_b))
        assert foreign_resp.status_code == 404, (
            f"{url} leaked resource {resource_id} to a foreign tenant: "
            f"got {foreign_resp.status_code} instead of 404"
        )

        open_mode_resp = client.get(url)
        assert open_mode_resp.status_code == 404, (
            f"{url} leaked resource {resource_id} to the open-mode/default tenant"
        )


def test_whitelist_entry_delete_is_tenant_scoped(client, two_tenants):
    tenant_a, key_a, tenant_b, key_b = two_tenants

    add = client.post(
        "/api/v1/whitelist",
        data={
            "brand": "IsoWhitelistBrand",
            "seller_name": "IsoWhitelistSeller",
            "marketplace": "WB",
            "note": "",
        },
        headers=_headers(key_a),
    )
    assert add.status_code == 200, add.text
    entry_id = add.json()["id"]

    # Foreign tenant cannot delete it — 404, and the row must survive.
    foreign_delete = client.delete(
        f"/api/v1/whitelist/{entry_id}", headers=_headers(key_b)
    )
    assert foreign_delete.status_code == 404

    still_there = client.get("/api/v1/whitelist", headers=_headers(key_a)).json()
    assert any(e["id"] == entry_id for e in still_there["entries"])

    # Owner can delete it.
    owner_delete = client.delete(
        f"/api/v1/whitelist/{entry_id}", headers=_headers(key_a)
    )
    assert owner_delete.status_code == 200
