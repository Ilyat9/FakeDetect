import aiosqlite
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "fakedetect.db")

# Versioned migrations applied at startup (in order). Append new tuples to
# change the schema — never edit already-applied entries.
# For Postgres production deployments use SQLAlchemy async + Alembic instead
# (see README "Миграции").
MIGRATIONS: list = [
    (
        1,
        "block A: prompt versioning columns on checks",
        [
            "ALTER TABLE checks ADD COLUMN prompt_version TEXT",
            "ALTER TABLE checks ADD COLUMN prompt_hash TEXT",
        ],
    ),
    (
        2,
        "block B: forensic signals and composite score on checks",
        [
            "ALTER TABLE checks ADD COLUMN ela_score REAL",
            "ALTER TABLE checks ADD COLUMN ela_flag INTEGER",
            "ALTER TABLE checks ADD COLUMN exif_flags TEXT",
            "ALTER TABLE checks ADD COLUMN final_score REAL",
            "ALTER TABLE checks ADD COLUMN score_components TEXT",
            "ALTER TABLE checks ADD COLUMN phash TEXT",
            "ALTER TABLE checks ADD COLUMN verdict_source TEXT",
            "ALTER TABLE checks ADD COLUMN consensus TEXT",
            "ALTER TABLE checks ADD COLUMN raw_model_responses TEXT",
        ],
    ),
    (
        3,
        "block D: evidence chain-of-custody hashes on checks",
        [
            "ALTER TABLE checks ADD COLUMN evidence_files TEXT",
        ],
    ),
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

            # request_cache — идемпотентность анализа (Block A.2): повторный
            # запрос с тем же request_id возвращает сохранённый результат,
            # не тратя второй раз деньги на LLM.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS request_cache (
                    request_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # retry_queue — отложенная обработка, когда все LLM-провайдеры
            # недоступны (Block A.6): 202 + polling вместо мгновенного 500.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS retry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',   -- pending|processing|done|failed
                    attempts INTEGER DEFAULT 0,
                    next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_retry_queue_due "
                "ON retry_queue(status, next_attempt_at)"
            )

            # image_hashes — перцептивные хэши всех изображений (Block B.1):
            # мгновенные вердикты для дубликатов, reverse image search,
            # дедупликация discovery (Block C).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS image_hashes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phash TEXT NOT NULL,
                    source_type TEXT NOT NULL,      -- 'reference' | 'suspect'
                    verdict TEXT,
                    confidence INTEGER,
                    summary TEXT,
                    related_check_id INTEGER,
                    image_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_image_hashes_phash ON image_hashes(phash)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_image_hashes_source ON image_hashes(source_type)"
            )

            # brand_watches — мониторинг бренда (Block C.1): ключевые слова,
            # площадки, cron-расписание скана, эталонные изображения.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS brand_watches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand_name TEXT NOT NULL,
                    keywords TEXT NOT NULL,             -- comma-separated
                    marketplaces TEXT DEFAULT 'WB',     -- comma-separated
                    cron_schedule TEXT DEFAULT '0 7 * * *',
                    digest_interval_hours INTEGER DEFAULT 24,
                    is_active INTEGER DEFAULT 1,
                    last_run_at TIMESTAMP,
                    next_run_at TIMESTAMP,
                    last_status TEXT,
                    last_digest_at TIMESTAMP,
                    reference_images TEXT,              -- JSON array of base64
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # discovery_listings — найденные карточки (Block C.3): дедупликация
            # по URL/SKU + TTL повторной проверки в зависимости от вердикта.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS discovery_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    sku TEXT,
                    title TEXT,
                    price REAL,
                    seller TEXT,
                    thumbnail_url TEXT,
                    status TEXT DEFAULT 'new',   -- new|analyzed|skipped_duplicate|error
                    verdict TEXT,
                    confidence INTEGER,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked_at TIMESTAMP,
                    UNIQUE(watch_id, url)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_discovery_listings_watch "
                "ON discovery_listings(watch_id, status)"
            )

            # cases — workflow кейсов (Block D.3): статус-машина поверх checks.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    check_id INTEGER NOT NULL UNIQUE,
                    url TEXT,
                    brand TEXT,
                    marketplace TEXT,
                    seller TEXT,
                    verdict TEXT,
                    status TEXT DEFAULT 'DETECTED',
                    assignee TEXT,
                    sla_deadline TIMESTAMP,
                    last_escalated_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cases_sla ON cases(status, sla_deadline)"
            )

            # case_status_history — журнал всех переходов статуса (аудит).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS case_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    changed_by TEXT,
                    comment TEXT,
                    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # case_comments — комментарии сотрудников по кейсу.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS case_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER NOT NULL,
                    author TEXT,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

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


def _to_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


async def save_check(result: dict) -> int:
    """Save check result to database (Block A.8 fingerprint + Block B forensics)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO checks
                   (url, brand, marketplace, verdict, confidence, risk_level, summary,
                    price_original, price_suspect, result_icon, seller,
                    prompt_version, prompt_hash,
                    ela_score, ela_flag, exif_flags, final_score, score_components,
                    phash, verdict_source, consensus, raw_model_responses)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    result.get('seller'),
                    result.get('prompt_version'),
                    result.get('prompt_hash'),
                    result.get('ela_score'),
                    1 if result.get('ela_flag') else 0,
                    _to_json(result.get('exif_flags')),
                    result.get('final_score'),
                    _to_json(result.get('score_components')),
                    result.get('phash'),
                    result.get('verdict_source'),
                    result.get('consensus'),
                    _to_json(result.get('raw_model_responses')),
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


# --- idempotency cache (Block A.2) --------------------------------------------


async def cache_get_result(request_id: str, ttl_hours: int = 24) -> Optional[Dict[str, Any]]:
    """Return cached analysis result for request_id, or None if absent/expired."""
    if not request_id:
        return None
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT result_json FROM request_cache "
                "WHERE request_id = ? AND created_at >= datetime('now', ?)",
                (request_id, f"-{ttl_hours} hours"),
            )
            row = await cursor.fetchone()
            return json.loads(row["result_json"]) if row else None
    except Exception as e:
        logger.error(f"Idempotency lookup failed for {request_id}: {e}")
        return None


async def cache_put_result(request_id: str, result: Dict[str, Any], ttl_hours: int = 24) -> None:
    """Store the verdict under request_id; opportunistically evict expired rows."""
    if not request_id:
        return
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO request_cache (request_id, result_json) VALUES (?, ?)",
                (request_id, json.dumps(result, ensure_ascii=False)),
            )
            await db.execute(
                "DELETE FROM request_cache WHERE created_at < datetime('now', ?)",
                (f"-{ttl_hours} hours",),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Idempotency store failed for {request_id}: {e}")


# --- retry queue (Block A.6) ----------------------------------------------------


async def enqueue_retry(request_id: str, payload: Dict[str, Any]) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO retry_queue (request_id, payload_json) VALUES (?, ?)",
                (request_id, json.dumps(payload, ensure_ascii=False)),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to enqueue retry {request_id}: {e}")


async def get_queue_item(request_id: str) -> Optional[Dict[str, Any]]:
    """Queue row by request_id; for 'done' items the cached result is attached."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM retry_queue WHERE request_id = ?", (request_id,)
            )
            row = await cursor.fetchone()
            item = dict(row) if row else None
            if item and item.get("status") == "done":
                cursor2 = await db.execute(
                    "SELECT result_json FROM request_cache WHERE request_id = ?",
                    (request_id,),
                )
                r2 = await cursor2.fetchone()
                item["result"] = json.loads(r2["result_json"]) if r2 else None
            return item
    except Exception as e:
        logger.error(f"Failed to get queue item {request_id}: {e}")
        return None


async def get_due_retries(limit: int = 3) -> List[Dict[str, Any]]:
    """Pending items whose backoff window has elapsed."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM retry_queue WHERE status = 'pending' "
                "AND next_attempt_at <= datetime('now') ORDER BY next_attempt_at LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch due retries: {e}")
        return []


async def _update_retry(request_id: str, fields: Dict[str, Any]) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [request_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE retry_queue SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE request_id = ?",
            values,
        )
        await db.commit()


async def mark_retry_processing(request_id: str) -> None:
    try:
        await _update_retry(request_id, {"status": "processing"})
    except Exception as e:
        logger.error(f"Failed to mark processing {request_id}: {e}")


async def mark_retry_done(request_id: str, result: Dict[str, Any]) -> None:
    try:
        await cache_put_result(request_id, result)
        await _update_retry(request_id, {"status": "done", "last_error": None})
    except Exception as e:
        logger.error(f"Failed to mark done {request_id}: {e}")


async def mark_retry_failed(
    request_id: str, error: str, attempts: int, max_attempts: int
) -> None:
    """Exponential backoff (1/2/4/8... minutes); terminal 'failed' after max_attempts."""
    try:
        new_attempts = attempts + 1
        if new_attempts >= max_attempts:
            await _update_retry(request_id, {
                "status": "failed",
                "attempts": new_attempts,
                "last_error": error[:500],
            })
        else:
            backoff_minutes = 2 ** min(attempts, 5)
            next_attempt = (
                datetime.utcnow() + timedelta(minutes=backoff_minutes)
            ).strftime("%Y-%m-%d %H:%M:%S")
            await _update_retry(request_id, {
                "status": "pending",
                "attempts": new_attempts,
                "last_error": error[:500],
                "next_attempt_at": next_attempt,
            })
    except Exception as e:
        logger.error(f"Failed to mark failed {request_id}: {e}")


async def count_retry_queue(status: Optional[str] = None) -> int:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            if status:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM retry_queue WHERE status = ?", (status,)
                )
            else:
                cursor = await db.execute("SELECT COUNT(*) FROM retry_queue")
            row = await cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"Failed to count retry queue: {e}")
        return 0


# --- perceptual hashes (Block B.1) -----------------------------------------------


async def save_image_hash(
    phash: str,
    source_type: str,
    verdict: Optional[str] = None,
    confidence: Optional[int] = None,
    summary: Optional[str] = None,
    related_check_id: Optional[int] = None,
    image_url: Optional[str] = None,
) -> int:
    """Store a perceptual hash. Returns row id (0 on failure)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO image_hashes
                   (phash, source_type, verdict, confidence, summary,
                    related_check_id, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (phash, source_type, verdict, confidence, summary,
                 related_check_id, image_url),
            )
            await db.commit()
            row = await db.execute("SELECT last_insert_rowid()")
            r = await row.fetchone()
            return r[0] if r else 0
    except Exception as e:
        logger.error(f"Failed to save image hash: {e}")
        return 0


async def find_similar_suspect_hash(
    phash: str, max_distance: int = 8
) -> Optional[Dict[str, Any]]:
    """Nearest already-classified suspect hash within max_distance (hamming).

    SQLite cannot compute popcount in SQL, so candidates are scanned in Python;
    the table is bounded by classified images only, which keeps it fast at the
    current scale (see ARCHITECTURE.md for the pgvector/Faiss upgrade path).
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, phash, verdict, confidence, summary, related_check_id "
                "FROM image_hashes "
                "WHERE source_type = 'suspect' AND verdict IS NOT NULL"
            )
            rows = await cursor.fetchall()

        from forensics.phash import hamming_distance

        best = None
        best_distance = max_distance + 1
        for row in rows:
            distance = hamming_distance(phash, row["phash"])
            if distance < best_distance:
                best_distance = distance
                best = dict(row)
        if best and best_distance <= max_distance:
            best["hamming_distance"] = best_distance
            return best
        return None
    except Exception as e:
        logger.error(f"Similar-hash lookup failed: {e}")
        return None


async def find_similar_images(
    phash: str, max_distance: int = 8, limit: int = 50
) -> List[Dict[str, Any]]:
    """Reverse image search across ALL stored hashes (both source types).

    Joins to checks to expose url/brand/marketplace of matching cases.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT h.id, h.phash, h.source_type, h.verdict, h.confidence, "
                "h.related_check_id, c.url, c.brand, c.marketplace, c.checked_at "
                "FROM image_hashes h LEFT JOIN checks c ON c.id = h.related_check_id"
            )
            rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"Reverse image search failed: {e}")
        return []

    from forensics.phash import hamming_distance

    matches = []
    for row in rows:
        distance = hamming_distance(phash, row["phash"])
        if distance <= max_distance:
            item = dict(row)
            item["hamming_distance"] = distance
            matches.append(item)
    matches.sort(key=lambda m: m["hamming_distance"])
    return matches[:limit]


# --- brand watches (Block C.1) ----------------------------------------------------


async def create_brand_watch(
    brand_name: str,
    keywords_csv: str,
    marketplaces_csv: str,
    cron_schedule: str,
    digest_interval_hours: int,
    reference_images_json: str,
) -> int:
    """Create a brand watch. Returns its id (-1 on failure)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO brand_watches
                   (brand_name, keywords, marketplaces, cron_schedule,
                    digest_interval_hours, reference_images)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (brand_name, keywords_csv, marketplaces_csv, cron_schedule,
                 digest_interval_hours, reference_images_json),
            )
            await db.commit()
            row = await db.execute("SELECT last_insert_rowid()")
            r = await row.fetchone()
            return r[0] if r else -1
    except Exception as e:
        logger.error(f"Failed to create brand watch: {e}")
        return -1


async def get_brand_watch(watch_id: int) -> Optional[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM brand_watches WHERE id = ?", (watch_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get brand watch {watch_id}: {e}")
        return None


async def get_brand_watches(active_only: bool = True) -> List[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM brand_watches"
            if active_only:
                query += " WHERE is_active = 1"
            cursor = await db.execute(query)
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list brand watches: {e}")
        return []


async def delete_brand_watch(watch_id: int) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM brand_watches WHERE id = ?", (watch_id,)
            )
            await db.execute("DELETE FROM discovery_listings WHERE watch_id = ?", (watch_id,))
            await db.commit()
            return bool(cursor.rowcount)
    except Exception as e:
        logger.error(f"Failed to delete brand watch {watch_id}: {e}")
        return False


async def set_watch_run_state(
    watch_id: int,
    last_status: Optional[str] = None,
    next_run_at: Optional[str] = None,
    mark_run: bool = False,
    digest_sent: bool = False,
) -> None:
    fields: List[Any] = []
    sets = []
    if last_status is not None:
        sets.append("last_status = ?")
        fields.append(last_status)
    if next_run_at is not None:
        sets.append("next_run_at = ?")
        fields.append(next_run_at)
    if mark_run:
        sets.append("last_run_at = CURRENT_TIMESTAMP")
    if digest_sent:
        sets.append("last_digest_at = CURRENT_TIMESTAMP")
    if not sets:
        return
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE brand_watches SET {', '.join(sets)} WHERE id = ?",
                [*fields, watch_id],
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to update run state for watch {watch_id}: {e}")


async def get_due_watches(now_str: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Active watches whose next_run_at has passed (or was never computed)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM brand_watches WHERE is_active = 1 "
                "AND (next_run_at IS NULL OR next_run_at <= ?) LIMIT ?",
                (now_str, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch due watches: {e}")
        return []


# --- discovery listings (Block C.3) -------------------------------------------------


async def upsert_listing(watch_id: int, url: str, **fields: Any) -> tuple:
    """Insert or refresh a discovered listing. Returns (id, created).

    Discovery metadata (sku/title/price/seller) is refreshed on re-find;
    the analysis state (verdict/status) is preserved.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT id FROM discovery_listings WHERE watch_id = ? AND url = ?",
                (watch_id, url),
            )
            existing = await cursor.fetchone()
            if existing:
                listing_pk = existing[0]
                await db.execute(
                    """UPDATE discovery_listings SET
                       sku = COALESCE(?, sku), title = COALESCE(?, title),
                       price = COALESCE(?, price), seller = COALESCE(?, seller)
                       WHERE id = ?""",
                    (fields.get("sku"), fields.get("title"), fields.get("price"),
                     fields.get("seller"), listing_pk),
                )
                await db.commit()
                return listing_pk, False

            await db.execute(
                """INSERT INTO discovery_listings
                   (watch_id, url, sku, title, price, seller, thumbnail_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (watch_id, url, fields.get("sku"), fields.get("title"),
                 fields.get("price"), fields.get("seller"), fields.get("thumbnail_url")),
            )
            await db.commit()
            row = await db.execute("SELECT last_insert_rowid()")
            r = await row.fetchone()
            return (r[0] if r else 0), True
    except Exception as e:
        logger.error(f"Failed to upsert listing {url}: {e}")
        return 0, False


async def update_listing_analysis(
    listing_id: int, verdict: Optional[str], confidence: Optional[int],
    status: str = "analyzed",
) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE discovery_listings SET verdict = ?, confidence = ?, "
                "status = ?, last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                (verdict, confidence, status, listing_id),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to update listing {listing_id}: {e}")


async def listing_needs_recheck(
    watch_id: int, url: str,
    original_days: int, suspicious_days: int, fake_days: int,
) -> bool:
    """C.3 dedup TTL: skip URLs analyzed recently; TTL depends on verdict.

    ОРИГИНАЛ → longest TTL, ПОДОЗРИТЕЛЬНО → medium, ПОДДЕЛКА → shortest.
    Fails open: on any error we prefer re-analyzing over silently skipping.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT status, verdict, last_checked_at FROM discovery_listings "
                "WHERE watch_id = ? AND url = ?",
                (watch_id, url),
            )
            row = await cursor.fetchone()
            if not row or row["status"] != "analyzed":
                return True
            ttl_by_verdict = {
                "ОРИГИНАЛ": original_days,
                "ПОДОЗРИТЕЛЬНО": suspicious_days,
                "ПОДДЕЛКА": fake_days,
            }
            days = ttl_by_verdict.get(row["verdict"], suspicious_days)
            if days <= 0 or not row["last_checked_at"]:
                return True
            cursor = await db.execute(
                "SELECT (julianday('now') - julianday(?)) >= ?",
                (row["last_checked_at"], days),
            )
            expired = (await cursor.fetchone())[0]
        return bool(expired)
    except Exception as e:
        logger.error(f"Recheck check failed for {url}: {e}")
        return True


async def get_watch_listings(watch_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM discovery_listings WHERE watch_id = ? "
                "ORDER BY first_seen_at DESC LIMIT ?",
                (watch_id, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list watch listings: {e}")
        return []


async def get_recent_findings(watch_id: int, since_hours: int) -> List[Dict[str, Any]]:
    """Listings with fake/suspicious verdicts since N hours ago (digest source)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT url, title, price, seller, verdict, confidence, last_checked_at "
                "FROM discovery_listings WHERE watch_id = ? "
                "AND verdict IN ('ПОДДЕЛКА', 'ПОДОЗРИТЕЛЬНО') "
                "AND last_checked_at >= datetime('now', ?) "
                "ORDER BY last_checked_at DESC",
                (watch_id, f"-{since_hours} hours"),
            )
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch findings: {e}")
        return []


# --- cases workflow (Block D) ------------------------------------------------------


async def get_check_row(check_id: int) -> Optional[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM checks WHERE id = ?", (check_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get check {check_id}: {e}")
        return None


async def create_case_from_check(check_id: int, sla_hours: Optional[int] = None) -> int:
    """Create (or return existing) case for a check. Returns case id."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id FROM cases WHERE check_id = ?", (check_id,)
            )
            existing = await cursor.fetchone()
            if existing:
                return existing["id"]

            check = None
            c = await db.execute("SELECT url, brand, marketplace, seller, verdict "
                                 "FROM checks WHERE id = ?", (check_id,))
            check = await c.fetchone()
            if not check:
                return -1

            sla_clause = ""
            params: List[Any] = [
                check_id, check["url"], check["brand"], check["marketplace"],
                check["seller"], check["verdict"],
            ]
            if sla_hours:
                sla_clause = ", sla_deadline = datetime('now', ?)"
                params.append(f"+{sla_hours} hours")

            cursor = await db.execute(
                f"""INSERT INTO cases (check_id, url, brand, marketplace, seller,
                       verdict{', sla_deadline' if sla_hours else ''})
                   VALUES (?, ?, ?, ?, ?, ?{', ?' if sla_hours else ''})""",
                params,
            )
            await db.commit()
            row = await db.execute("SELECT last_insert_rowid()")
            case_id = (await row.fetchone())[0]
            await db.execute(
                "INSERT INTO case_status_history (case_id, from_status, to_status, changed_by) "
                "VALUES (?, NULL, 'DETECTED', 'system:auto')",
                (case_id,),
            )
            await db.commit()
            return case_id
    except Exception as e:
        logger.error(f"Failed to create case for check {check_id}: {e}")
        return -1


async def get_case(case_id: int) -> Optional[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM cases WHERE id = ?", (case_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get case {case_id}: {e}")
        return None


async def get_case_by_check(check_id: int) -> Optional[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM cases WHERE check_id = ?", (check_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get case by check {check_id}: {e}")
        return None


async def list_cases(
    status: Optional[str] = None,
    brand: Optional[str] = None,
    seller: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    query = "SELECT * FROM cases WHERE 1=1"
    params: List[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if brand:
        query += " AND brand LIKE ?"
        params.append(f"%{brand}%")
    if seller:
        query += " AND seller LIKE ?"
        params.append(f"%{seller}%")
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list cases: {e}")
        return []


CASE_TRANSITIONS = {
    # from → allowed next statuses
    "DETECTED": {"UNDER_REVIEW", "CONFIRMED_FAKE", "FALSE_POSITIVE",
                 "REQUIRES_MANUAL_REVIEW", "CLOSED"},
    "UNDER_REVIEW": {"CONFIRMED_FAKE", "FALSE_POSITIVE", "REQUIRES_MANUAL_REVIEW",
                     "COMPLAINT_FILED"},
    "REQUIRES_MANUAL_REVIEW": {"UNDER_REVIEW", "CONFIRMED_FAKE", "FALSE_POSITIVE"},
    "CONFIRMED_FAKE": {"COMPLAINT_FILED", "CLOSED", "FALSE_POSITIVE"},
    "FALSE_POSITIVE": {"CLOSED"},
    "COMPLAINT_FILED": {"LISTING_REMOVED", "CLOSED"},
    "LISTING_REMOVED": {"CLOSED"},
    "CLOSED": set(),
}

# SLA per status (hours): how long a case may sit in this state.
DEFAULT_SLA_HOURS = {
    "DETECTED": 24,
    "UNDER_REVIEW": 72,
    "REQUIRES_MANUAL_REVIEW": 48,
    "CONFIRMED_FAKE": 72,
    "COMPLAINT_FILED": 168,
}


async def transition_case(
    case_id: int,
    to_status: str,
    changed_by: str = "user",
    comment: Optional[str] = None,
) -> tuple:
    """Validate and apply a status transition. Returns (ok, error_or_case)."""
    case = await get_case(case_id)
    if not case:
        return False, "Case not found"
    current = case["status"]
    if to_status == current:
        return False, f"Case is already in '{current}'"
    allowed = CASE_TRANSITIONS.get(current, set())
    if to_status not in allowed:
        return False, (
            f"Transition {current} → {to_status} is not allowed. "
            f"Allowed: {sorted(allowed) or 'none (terminal status)'}"
        )

    sla = DEFAULT_SLA_HOURS.get(to_status)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            sets = "status = ?, updated_at = CURRENT_TIMESTAMP"
            params: List[Any] = [to_status]
            if sla:
                sets += ", sla_deadline = datetime('now', ?)"
                params.append(f"+{sla} hours")
            else:
                sets += ", sla_deadline = NULL"
            params.append(case_id)
            await db.execute(f"UPDATE cases SET {sets} WHERE id = ?", params)
            await db.execute(
                "INSERT INTO case_status_history "
                "(case_id, from_status, to_status, changed_by, comment) "
                "VALUES (?, ?, ?, ?, ?)",
                (case_id, current, to_status, changed_by, comment),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to transition case {case_id}: {e}")
        return False, str(e)

    return True, await get_case(case_id)


async def add_case_comment(case_id: int, author: str, text: str) -> int:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO case_comments (case_id, author, text) VALUES (?, ?, ?)",
                (case_id, author, text),
            )
            await db.commit()
            row = await db.execute("SELECT last_insert_rowid()")
            return (await row.fetchone())[0]
    except Exception as e:
        logger.error(f"Failed to add comment to case {case_id}: {e}")
        return -1


async def get_case_comments(case_id: int) -> List[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM case_comments WHERE case_id = ? ORDER BY created_at",
                (case_id,),
            )
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list comments for case {case_id}: {e}")
        return []


async def get_case_history(case_id: int) -> List[Dict[str, Any]]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM case_status_history WHERE case_id = ? ORDER BY changed_at",
                (case_id,),
            )
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get history for case {case_id}: {e}")
        return []


async def assign_case(case_id: int, assignee: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE cases SET assignee = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (assignee, case_id),
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Failed to assign case {case_id}: {e}")
        return False


async def get_overdue_cases(limit: int = 50) -> List[Dict[str, Any]]:
    """Open cases whose SLA deadline has passed."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM cases WHERE sla_deadline IS NOT NULL "
                "AND status NOT IN ('CLOSED', 'LISTING_REMOVED') "
                "AND sla_deadline <= datetime('now') LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch overdue cases: {e}")
        return []


async def mark_escalated(case_ids: List[int]) -> None:
    if not case_ids:
        return
    placeholders = ",".join("?" for _ in case_ids)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE cases SET last_escalated_at = CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})",
                case_ids,
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to mark escalated cases: {e}")


async def update_check_evidence(check_id: int, evidence_files_json: str) -> bool:
    """Store the chain-of-custody manifest on the check row (Block D.1)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE checks SET evidence_files = ? WHERE id = ?",
                (evidence_files_json, check_id),
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Failed to store evidence manifest for check {check_id}: {e}")
        return False


async def get_price_history(url: str, limit: int = 20) -> List[Dict[str, Any]]:
    """All checks of the same listing URL over time (for the evidence PDF)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT checked_at, price_suspect, verdict FROM checks "
                "WHERE url = ? ORDER BY checked_at DESC LIMIT ?",
                (url, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch price history for {url}: {e}")
        return []



