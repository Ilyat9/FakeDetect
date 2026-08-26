"""Locust load-test scenarios (Block A.7).

Run against a LOCAL/staging deployment:

    pip install -r loadtests/requirements-loadtest.txt
    locust -f loadtests/locustfile.py --host http://localhost:8000

Then open http://localhost:8089 and start e.g. 20 users, ramp 2/s.
Document the resulting p50/p95/p99 in README "SLO".
"""

import io

from locust import HttpUser, between, task


def _generate_tiny_png() -> bytes:
    """64x64 valid PNG generated once per worker process."""
    from PIL import Image

    img = Image.new("RGB", (64, 64), (120, 30, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


TINY_PNG = _generate_tiny_png()


class AnalyzeUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(5)
    def analyze_single(self):
        self.client.post(
            "/api/v1/analyze",
            files={
                "original": ("o.png", TINY_PNG, "image/png"),
                "suspect": ("s.png", TINY_PNG, "image/png"),
            },
            data={"brand": "LoadTest"},
            name="/api/v1/analyze",
        )

    @task(3)
    def health(self):
        self.client.get("/health", name="/health")

    @task(2)
    def history(self):
        self.client.get("/api/v1/history?limit=10", name="/api/v1/history")
