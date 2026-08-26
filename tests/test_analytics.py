"""Block E tests: analytics endpoints, ROI metrics, PDF/PPTX export."""

import base64
import io
import uuid

import pytest
from PIL import Image
from pydantic import SecretStr

from app.core import llm_gateway as gateway
from app.core.config import settings
from tests.test_tenancy import _issue_key, _make_tenant


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
def fake_llm(monkeypatch):
    async def fake(orig, sus, meta, preferred_provider=None):
        return (
            {"verdict": "ПОДДЕЛКА", "confidence": 92, "summary": "fake",
             "risk_level": "high",
             "indicators": [{"factor": "logo", "score": 1, "status": "fail",
                             "detail": "mismatch"}]},
            {"provider": "gemini", "verdict_source": "llm_analysis"},
        )

    monkeypatch.setattr(gateway, "analyze_resilient", fake)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("k"))
    yield


def _analyze(client, seller, price_original, price_suspect, brand="AnalyticsBrand"):
    rid = uuid.uuid4().hex
    res = client.post("/api/v1/analyze", files={
        "original": ("o.png", _png((0, 0, 0)), "image/png"),
        "suspect": ("s.png", _png((hash(seller) % 200, 50, 90)), "image/png"),
    }, data={
        "brand": brand,
        "seller": seller,
        "url": f"https://www.wildberries.ru/catalog/{rid[:8]}/detail.aspx",
        "price_original": price_original,
        "price_suspect": price_suspect,
    }, headers={"X-Request-ID": rid})
    assert res.status_code == 200, res.text
    return res.json()


def test_timeseries_and_invalid_granularity(client, fake_llm):
    _analyze(client, seller="SellerA", price_original=5000, price_suspect=800)

    r = client.get("/api/v1/analytics/timeseries",
                   params={"granularity": "day", "days": 7})
    assert r.status_code == 200
    points = r.json()["points"]
    assert points, "expected at least one bucket"
    today_bucket = next(p for p in points if p["fakes"] >= 1)
    assert today_bucket["total"] == today_bucket["fakes"] + \
        today_bucket["originals"] + today_bucket["suspicious"]

    bad = client.get("/api/v1/analytics/timeseries", params={"granularity": "hour"})
    assert bad.status_code == 422


def test_top_sellers_ranked_by_fakes(client, fake_llm):
    _analyze(client, seller="WorstSeller", price_original=5000, price_suspect=700)
    _analyze(client, seller="WorstSeller", price_original=5000, price_suspect=700)
    _analyze(client, seller="MinorSeller", price_original=4000, price_suspect=600)

    r = client.get("/api/v1/analytics/top-sellers").json()
    sellers = {s["seller"]: s for s in r["sellers"]}
    assert sellers["WorstSeller"]["fakes"] == 2
    assert sellers["MinorSeller"]["fakes"] == 1
    ranked = [s["seller"] for s in r["sellers"]]
    assert ranked.index("WorstSeller") < ranked.index("MinorSeller")


def test_protected_revenue_estimate_and_disclaimer(client, fake_llm):
    brand = f"RevBrand-{uuid.uuid4().hex[:6]}"
    _analyze(client, seller="RevSeller", price_original=5000,
             price_suspect=700, brand=brand)
    _analyze(client, seller="RevSeller", price_original=5000,
             price_suspect=700, brand=brand)

    rev = client.get("/api/v1/analytics/revenue",
                     params={"brand": brand}).json()
    assert rev["confirmed_fakes"] == 2, rev
    assert rev["avg_original_price"] == 5000, rev
    assert rev["protected_revenue_estimate"] == 10000, rev
    assert "Оценка" in rev["disclaimer"]


def test_timing_metrics_shape(client, fake_llm):
    _analyze(client, seller="TimeSeller", price_original=0, price_suspect=0)
    timing = client.get("/api/v1/analytics/timing").json()
    # Discovery-based TTD may be None without scans; keys must always exist.
    assert "time_to_detection_days" in timing
    assert "time_to_resolution_days" in timing
    assert "note" in timing


def test_summary_bundle(client, fake_llm):
    _analyze(client, seller="SumSeller", price_original=3000, price_suspect=500)
    data = client.get("/api/v1/analytics/summary").json()
    assert {"summary", "timeseries", "top_sellers", "protected_revenue",
            "timing"} <= set(data)


def test_pdf_and_pptx_exports(client, fake_llm):
    _analyze(client, seller="ExportSeller", price_original=5000, price_suspect=600)

    pdf = client.get("/api/v1/analytics/export.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"

    pptx = client.get("/api/v1/analytics/export.pptx")
    assert pptx.status_code == 200
    assert pptx.content[:2] == b"PK"          # OOXML zip magic


def test_analytics_tenant_scoped(client, fake_llm):
    _make_tenant("OtherCo")
    key_b = _issue_key("analyst", tenant_id=2)
    # Tenant B has no checks — its analytics must be empty even though the
    # shared session DB contains other tenants' data.
    ts = client.get("/api/v1/analytics/timeseries",
                    headers={"X-API-Key": key_b}).json()["points"]
    assert ts == []
    stats = client.get("/api/v1/partner/stats",
                       headers={"X-API-Key": key_b}).json()
    assert stats["stats"]["total"] == 0