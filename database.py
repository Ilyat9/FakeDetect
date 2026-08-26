import aiosqlite
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "fakedetect.db")

# Versioned migrations applied at startup (in order). Append new tuples to
# change the schema — never edit already-applied entries.
# For Postgres production deployments use SQLAlchemy async + Alembic instead
# (see README "Миграции").
MIGRATIONS: list = [
    # Example format:
    # (1, "add seller column", ["ALTER TABLE checks ADD COLUMN seller TEXT"]),
]


async def _apply_migrations(db) -> None:
    """Apply pending schema migrations, tracked in schema_migrations table."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    row = await cursor.fetchone()
    current_version = row[0] if row else 0

    for version, description, statements in MIGRATIONS:
        if version <= current_version:
            continue
        logger.info(f"Applying migration #{version}: {description}")
        for statement in statements:
            await db.execute(statement)
        await db.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (version, description)
        )

whitelist_seeds = [
    ("Nike", "Nike Official Store", "WB"),
    ("Nike", "Nike Russia", "Ozon"),
    ("Adidas", "Adidas Official", "WB"),
    ("Apple", "re:Store", "WB"),
    ("Apple", "Premium Store", "Ozon"),
]

brands_seeds = [
    ("Nike", "nike air force, nike air max, nike кроссовки"),
    ("Adidas", "adidas originals, adidas ultraboost"),
    ("Apple", "apple iphone, airpods apple"),
]


async def init_db() -> None:
    """Create tables and seed data if needed."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # checks — история всех проверок
            await db.execute("""
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT,
                    brand TEXT,
                    marketplace TEXT,
                    verdict TEXT,
                    confidence INTEGER,
                    risk_level TEXT,
                    summary TEXT,
                    price_original INTEGER,
                    price_suspect INTEGER,
                    result_icon TEXT,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    seller TEXT
                )
            """)

            # whitelist — авторизованные продавцы бренда
            await db.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand TEXT NOT NULL,
                    seller_name TEXT NOT NULL,
                    marketplace TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    note TEXT
                )
            """)

            # brands — бренды которые мониторим
            await db.execute("""
                CREATE TABLE IF NOT EXISTS brands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    keywords TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # batch_tasks — фоновые задачи батч-обработки (персистентное хранилище)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS batch_tasks (
                    id TEXT PRIMARY KEY,
                    total INTEGER DEFAULT 0,
                    done INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'processing',
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result_file_path TEXT
                )
            """)

            # Индексы для частых запросов
            await db.execute("CREATE INDEX IF NOT EXISTS idx_checks_brand ON checks(brand)")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_checks_checked_at ON checks(checked_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_whitelist_lookup "
                "ON whitelist(seller_name, brand, marketplace)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_tasks_created_at ON batch_tasks(created_at)"
            )

            # WAL-режим для конкурентного доступа на чтение/запись
            await db.execute("PRAGMA journal_mode=WAL")

            # Seed whitelist if empty
            cursor = await db.execute("SELECT COUNT(*) FROM whitelist")
            row = await cursor.fetchone()
            count = row[0] if row else 0
            if count == 0:
                for brand, seller, mp in whitelist_seeds:
                    await db.execute(
                        "INSERT INTO whitelist (brand, seller_name, marketplace) VALUES (?, ?, ?)",
                        (brand, seller, mp)
                    )
                logger.info(f"Seeded {len(whitelist_seeds)} whitelist entries")

            # Seed brands if empty
            cursor = await db.execute("SELECT COUNT(*) FROM brands")
            row = await cursor.fetchone()
            count = row[0] if row else 0
            if count == 0:
                for name, keywords in brands_seeds:
                    await db.execute("INSERT INTO brands (name, keywords) VALUES (?, ?)", (name, keywords))
                logger.info(f"Seeded {len(brands_seeds)} brands")

            await db.commit()
            await _apply_migrations(db)
            await db.commit()
            logger.info("Database initialized")

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


async def save_check(result: dict) -> int:
    """Save check result to database."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO checks
                   (url, brand, marketplace, verdict, confidence, risk_level, summary,
                    price_original, price_suspect, result_icon, seller)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.get('url'),
                    result.get('brand'),
                    result.get('marketplace'),
                    result.get('verdict'),
                    result.get('confidence'),
                    result.get('risk_level'),
                    result.get('summary'),
                    result.get('price_original', 0),
                    result.get('price_suspect', 0),
                    result.get('result_icon'),
                    result.get('seller')
                )
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            row = await cursor.fetchone()
            check_id = row[0] if row else 0
            logger.info(f"Saved check #{check_id} to database")
            return check_id

    except Exception as e:
        logger.error(f"Failed to save check: {e}")
        return -1


async def get_checks(
    limit: int = 50, brand: Optional[str] = None, offset: int = 0
) -> tuple:
    """Get check history page and total count. Returns (checks, total)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            where = "WHERE brand = ?" if brand else ""
            params = [brand] if brand else []

            count_cursor = await db.execute(f"SELECT COUNT(*) FROM checks {where}", params)
            count_row = await count_cursor.fetchone()
            total = count_row[0] if count_row else 0

            query = (
                f"SELECT * FROM checks {where} "
                f"ORDER BY checked_at DESC, id DESC LIMIT ? OFFSET ?"
            )
            cursor = await db.execute(query, [*params, limit, max(offset, 0)])
            rows = await cursor.fetchall()

            return [dict(row) for row in rows], total

    except Exception as e:
        logger.error(f"Failed to get checks: {e}")
        return [], 0


async def is_whitelisted(seller: str, brand: str, marketplace: str) -> bool:
    """Check if seller is in whitelist."""
    try:
        seller = seller.strip().lower()
        brand = brand.strip().lower()
        marketplace = marketplace.strip().upper() if marketplace else ""

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """SELECT * FROM whitelist
                   WHERE LOWER(seller_name) = ?
                   AND (LOWER(brand) = ? OR brand = 'ALL')
                   AND (marketplace = ? OR marketplace = 'ALL' OR marketplace IS NULL)""",
                (seller, brand, marketplace)
            )
            row = await cursor.fetchone()
            return row is not None

    except Exception as e:
        logger.error(f"Failed to check whitelist: {e}")
        return False


async def add_to_whitelist(brand: str, seller_name: str, marketplace: str = "", note: str = "") -> int:
    """Add entry to whitelist. Returns the new row id, or -1 on failure."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO whitelist (brand, seller_name, marketplace, note) VALUES (?, ?, ?, ?)",
                (brand.strip(), seller_name.strip(), marketplace.strip(), note.strip())
            )
            await db.commit()
            entry_id = cursor.lastrowid
            logger.info(f"Added to whitelist #{entry_id}: {seller_name} ({brand})")
            return entry_id

    except Exception as e:
        logger.error(f"Failed to add to whitelist: {e}")
        return -1


async def get_whitelist(brand: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get whitelist entries."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            query = "SELECT * FROM whitelist"
            params = []
            if brand:
                query += " WHERE brand = ?"
                params.append(brand)
            query += " ORDER BY added_at DESC"

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            entries = []
            for row in rows:
                entries.append(dict(row))

            return entries

    except Exception as e:
        logger.error(f"Failed to get whitelist: {e}")
        return []


async def delete_from_whitelist(entry_id: int) -> bool:
    """Delete entry from whitelist."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("DELETE FROM whitelist WHERE id = ?", (entry_id,))
            await db.commit()

            if cursor.rowcount > 0:
                logger.info(f"Deleted whitelist entry #{entry_id}")
                return True
            return False

    except Exception as e:
        logger.error(f"Failed to delete from whitelist: {e}")
        return False


async def get_stats() -> Dict[str, int]:
    """Get statistics from database."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Total checks
            cursor = await db.execute("SELECT COUNT(*) FROM checks")
            row = await cursor.fetchone()
            total = row[0] if row else 0

            # Fakes
            cursor = await db.execute("SELECT COUNT(*) FROM checks WHERE verdict = 'ПОДДЕЛКА'")
            row = await cursor.fetchone()
            fakes = row[0] if row else 0

            # Originals
            cursor = await db.execute("SELECT COUNT(*) FROM checks WHERE verdict = 'ОРИГИНАЛ'")
            row = await cursor.fetchone()
            originals = row[0] if row else 0

            # Suspicious
            cursor = await db.execute("SELECT COUNT(*) FROM checks WHERE verdict = 'ПОДОЗРИТЕЛЬНО'")
            row = await cursor.fetchone()
            suspicious = row[0] if row else 0

            return {
                "total": total,
                "fakes": fakes,
                "originals": originals,
                "suspicious": suspicious
            }

    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {"total": 0, "fakes": 0, "originals": 0, "suspicious": 0}


# --- batch_tasks persistence -------------------------------------------------


async def create_batch_task(task_id: str, total: int) -> None:
    """Register a new batch task."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO batch_tasks (id, total, done, status) VALUES (?, ?, 0, 'processing')",
                (task_id, total)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to create batch task {task_id}: {e}")


async def increment_batch_task_progress(task_id: str) -> None:
    """Increment the done counter for a batch task."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE batch_tasks SET done = done + 1 WHERE id = ?", (task_id,)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to update progress for batch task {task_id}: {e}")


async def set_batch_task_status(
    task_id: str,
    status: str,
    error: Optional[str] = None,
    result_file_path: Optional[str] = None
) -> None:
    """Set final status for a batch task."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE batch_tasks SET status = ?, error = ?, result_file_path = ? WHERE id = ?",
                (status, error, result_file_path, task_id)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to set status for batch task {task_id}: {e}")


async def get_batch_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a batch task row (without internal fields like file path)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM batch_tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get batch task {task_id}: {e}")
        return None


async def get_batch_task_result_path(task_id: str) -> Optional[str]:
    """Fetch the xlsx result path for a completed batch task."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT result_file_path FROM batch_tasks WHERE id = ?", (task_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Failed to get result path for batch task {task_id}: {e}")
        return None


async def cleanup_old_batch_tasks(days: int = 7) -> int:
    """Delete batch tasks older than N days. Returns number of deleted rows."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM batch_tasks WHERE created_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            await db.commit()
            deleted = cursor.rowcount or 0
            if deleted:
                logger.info(f"Cleaned up {deleted} old batch tasks")
            return deleted
    except Exception as e:
        logger.error(f"Failed to cleanup old batch tasks: {e}")
        return 0
