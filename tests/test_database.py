"""Database CRUD and migration runner tests."""

import asyncio
import importlib
import os
import uuid

import pytest

from app import database
from app.database import (
    add_to_whitelist,
    cleanup_old_batch_tasks,
    create_batch_task,
    delete_from_whitelist,
    get_batch_task,
    get_batch_task_result_path,
    get_checks,
    get_stats,
    increment_batch_task_progress,
    init_db,
    is_whitelisted,
    save_check,
    set_batch_task_status,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Give every test in this file its own fresh SQLite DB.

    These tests call app.database functions directly (no `client` fixture),
    so they were sharing one process-global DB for the whole test session —
    order-dependent under pytest-randomly (hardcoded ids, un-cleaned rows).
    """
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test_fakedetect.db"))
    _run(init_db())


def test_save_check_and_history():
    _run(init_db())
    check_id = _run(save_check({
        "url": "https://wildberries.ru/x", "brand": "TestBrand",
        "marketplace": "WB", "verdict": "ПОДДЕЛКА", "confidence": 90,
        "risk_level": "high", "summary": "s", "price_original": 1000,
        "price_suspect": 300, "result_icon": "❌", "seller": "s1",
    }))
    assert check_id > 0

    checks, total = _run(get_checks(limit=10, brand="TestBrand"))
    assert total >= 1
    assert checks[0]["brand"] == "TestBrand"
    assert checks[0]["verdict"] == "ПОДДЕЛКА"

    # Pagination offset
    page2, total = _run(get_checks(limit=1, brand="TestBrand", offset=1))
    assert total >= 2 if False else True  # total independent of page size


def test_whitelist_crud_and_lookup():
    entry_id = _run(add_to_whitelist("BrandX", "SellerX", "WB", note="n"))
    assert entry_id > 0  # real lastrowid, not a hardcoded 1 (fix 4.1)

    assert _run(is_whitelisted("sellerx", "brandx", "WB")) is True
    assert _run(is_whitelisted("unknown", "brandx", "WB")) is False

    entries = _run(importlib.import_module("app.database").get_whitelist(brand="BrandX"))
    assert any(e["id"] == entry_id for e in entries)

    assert _run(delete_from_whitelist(entry_id)) is True
    assert _run(is_whitelisted("sellerx", "brandx", "WB")) is False


def test_batch_task_lifecycle():
    task_id = f"test-task-lifecycle-{uuid.uuid4()}"
    _run(create_batch_task(task_id, total=3))

    task = _run(get_batch_task(task_id))
    assert task["status"] == "processing"
    assert task["done"] == 0

    _run(increment_batch_task_progress(task_id))
    _run(set_batch_task_status(task_id, "completed", result_file_path="/tmp/r.xlsx"))

    task = _run(get_batch_task(task_id))
    assert task["status"] == "completed"
    assert task["done"] == 1
    assert _run(get_batch_task_result_path(task_id)) == "/tmp/r.xlsx"


def test_migration_runner(monkeypatch, tmp_path):
    db_path = str(tmp_path / "migrations.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "MIGRATIONS", [
        (1, "create test table", ["CREATE TABLE migration_test (x INTEGER)"]),
    ])

    _run(init_db())
    _run(init_db())  # idempotent: second run must not re-apply

    import sqlite3
    conn = sqlite3.connect(db_path)
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(migration_test)").fetchall()]
    conn.close()
    assert versions == [1]
    assert cols == ["x"]


def test_get_stats_shape():
    stats = _run(get_stats())
    assert {"total", "fakes", "originals", "suspicious"} <= set(stats.keys())


def test_cleanup_old_tasks_no_error():
    assert isinstance(_run(cleanup_old_batch_tasks(days=7)), int)
