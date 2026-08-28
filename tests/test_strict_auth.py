"""F-C5: open mode must warn loudly, and STRICT_AUTH=1 must refuse to boot
without API_SECRET_KEY instead of silently granting owner access to everyone.
"""

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import database
from app.core.config import settings


@pytest.fixture()
def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test_fakedetect.db"))


def test_strict_auth_startup_fails_without_key(_fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "strict_auth", True)
    monkeypatch.setattr(settings, "api_secret_key", None)

    from app.main import app

    with pytest.raises(Exception, match="STRICT_AUTH"):
        with TestClient(app):
            pass


def test_strict_auth_startup_succeeds_with_key(_fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "strict_auth", True)
    monkeypatch.setattr(settings, "api_secret_key", SecretStr("s3cr3t"))

    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200


def test_open_mode_without_strict_auth_warns_and_boots(_fresh_db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "strict_auth", False)
    monkeypatch.setattr(settings, "api_secret_key", None)

    from app.main import app

    with caplog.at_level(logging.WARNING, logger="app.main"):
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    assert any("OPEN MODE" in record.message for record in caplog.records)
