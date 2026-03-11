import aiosqlite
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = "fakedetect.db"

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


async def get_checks(limit: int = 50, brand: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get check history from database."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            if brand:
                query = "SELECT * FROM checks WHERE brand = ? ORDER BY checked_at DESC LIMIT ?"
                params = [brand, limit]
            else:
                query = "SELECT * FROM checks ORDER BY checked_at DESC LIMIT ?"
                params = [limit]

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            checks = []
            for row in rows:
                checks.append(dict(row))

            return checks

    except Exception as e:
        logger.error(f"Failed to get checks: {e}")
        return []


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
    """Add entry to whitelist."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO whitelist (brand, seller_name, marketplace, note) VALUES (?, ?, ?, ?)",
                (brand.strip(), seller_name.strip(), marketplace.strip(), note.strip())
            )
            await db.commit()
            logger.info(f"Added to whitelist: {seller_name} ({brand})")
            return 1

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
