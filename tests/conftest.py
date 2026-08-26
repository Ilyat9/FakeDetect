"""Shared pytest fixtures. Sets an isolated DB_PATH BEFORE any app import."""

import os
import tempfile

# Isolated database for the whole test session (must be set before imports).
_TEST_DB_DIR = tempfile.mkdtemp(prefix="fakedetect_tests_")
os.environ["DB_PATH"] = os.path.join(_TEST_DB_DIR, "test_fakedetect.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    """TestClient with app lifespan (startup initializes the isolated DB)."""
    from main import app
    with TestClient(app) as c:
        yield c
