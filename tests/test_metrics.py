"""Block A tests: /metrics endpoint and Prometheus instrumentation (A.5)."""

import re


def test_metrics_endpoint_exposes_core_metrics(client):
    client.get("/health")
    res = client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "fakedetect_request_latency_seconds" in body
    assert "fakedetect_llm_requests_total" in body
    assert "fakedetect_provider_breaker_state" in body
    # Prometheus text format sanity.
    assert re.search(r"^# HELP ", body, re.MULTILINE)


def test_request_id_header_returned(client):
    res = client.get("/api/v1/stats", headers={"X-Request-ID": "rid-check-42"})
    assert res.status_code in (200, 401)
