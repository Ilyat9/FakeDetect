"""Shared pytest fixtures.

Isolation strategy: EVERY test that uses `client` gets a fresh SQLite
database (tmp_path) by mutating app.database.DB_PATH before the app startup
runs init_db(). No state leaks between tests — order-independence is a hard
requirement (see test_discovery_e2e / test_cases / test_evidence flakes).
"""

import os  # noqa: F401  (kept: DB_PATH env fallback for non-client tests)
import tempfile

# Fallback DB for anything touched OUTSIDE the client fixture (must be set
# before imports). Real per-test isolation happens in the fixture below.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="fakedetect_tests_")
os.environ["DB_PATH"] = os.path.join(_TEST_DB_DIR, "test_fakedetect.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    """TestClient with app lifespan and a FRESH database per test."""
    from app import database
    from app.main import app

    db_path = str(tmp_path / "test_fakedetect.db")
    old_path = database.DB_PATH
    database.DB_PATH = db_path
    try:
        with TestClient(app) as c:
            yield c
    finally:
        database.DB_PATH = old_path
