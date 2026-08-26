# Load tests (Block A.7)

Locust scenarios for the FakeDetect API. Install:

```bash
pip install -r loadtests/requirements-loadtest.txt
```

Run against a local/staging server (**never** against production):

```bash
locust -f loadtests/locustfile.py --host http://localhost:8000
# headless variant with an immediate 60s run at 20 users:
locust -f loadtests/locustfile.py --host http://localhost:8000 \
       --headless -u 20 -r 2 -t 60s --csv loadtests/report
```

Scenarios:
- weight 5 — `POST /api/v1/analyze` (single image pair),
- weight 3 — `GET /health`,
- weight 2 — `GET /api/v1/history`.

Record p50/p95/p99 from the Locust UI or CSV and compare against the SLO table
in README.md ("Надёжность и SLO"). Update that table whenever capacity changes.
