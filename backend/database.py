"""
OrbitGuard Database — Supabase Postgres via asyncpg (sync wrapper)
Works on Python 3.14 — no C extensions needed.
"""

import os
import secrets
import hashlib
import logging
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _run(coro):
    """Run async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _get_conn():
    import asyncpg
    # Convert postgres:// to postgresql:// if needed
    url = DATABASE_URL.replace("postgres://", "postgresql://")
    return await asyncpg.connect(url)


def init_db():
    if not DATABASE_URL:
        _init_sqlite()
        return
    _run(_init_postgres())


async def _init_postgres():
    conn = await _get_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                key_hash TEXT UNIQUE NOT NULL,
                key_prefix TEXT NOT NULL,
                email TEXT NOT NULL,
                name TEXT,
                tier TEXT DEFAULT 'free',
                requests_today INTEGER DEFAULT 0,
                requests_total INTEGER DEFAULT 0,
                last_used TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_subscriptions (
                id SERIAL PRIMARY KEY,
                api_key_hash TEXT NOT NULL,
                email TEXT NOT NULL,
                norad_id INTEGER NOT NULL,
                satellite_name TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                elevation_m REAL DEFAULT 0.0,
                min_score INTEGER DEFAULT 60,
                alert_hours_ahead INTEGER DEFAULT 2,
                active INTEGER DEFAULT 1,
                last_alerted TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_log (
                id SERIAL PRIMARY KEY,
                subscription_id INTEGER NOT NULL,
                pass_aos TEXT NOT NULL,
                score REAL NOT NULL,
                grade TEXT NOT NULL,
                sent_at TEXT NOT NULL
            )
        """)
        logger.info("Postgres database initialized")
    finally:
        await conn.close()


def _init_sqlite():
    import sqlite3
    path = os.environ.get("DB_PATH", "./orbitguard.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT UNIQUE NOT NULL,
            key_prefix TEXT NOT NULL,
            email TEXT NOT NULL,
            name TEXT,
            tier TEXT DEFAULT 'free',
            requests_today INTEGER DEFAULT 0,
            requests_total INTEGER DEFAULT 0,
            last_used TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alert_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key_hash TEXT NOT NULL,
            email TEXT NOT NULL,
            norad_id INTEGER NOT NULL,
            satellite_name TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            elevation_m REAL DEFAULT 0.0,
            min_score INTEGER DEFAULT 60,
            alert_hours_ahead INTEGER DEFAULT 2,
            active INTEGER DEFAULT 1,
            last_alerted TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id INTEGER NOT NULL,
            pass_aos TEXT NOT NULL,
            score REAL NOT NULL,
            grade TEXT NOT NULL,
            sent_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    logger.info("SQLite database initialized")


# ── API Keys ──────────────────────────────────────────────────────────────────

def generate_api_key():
    raw = "og_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


def create_api_key(email: str, name: str = None, tier: str = "free") -> str:
    raw, key_hash = generate_api_key()
    prefix = raw[:10]
    now = datetime.now(timezone.utc).isoformat()
    if DATABASE_URL:
        _run(_create_api_key_pg(key_hash, prefix, email, name, tier, now))
    else:
        _create_api_key_sqlite(key_hash, prefix, email, name, tier, now)
    return raw


async def _create_api_key_pg(key_hash, prefix, email, name, tier, now):
    conn = await _get_conn()
    try:
        await conn.execute(
            "INSERT INTO api_keys (key_hash,key_prefix,email,name,tier,created_at) VALUES ($1,$2,$3,$4,$5,$6)",
            key_hash, prefix, email, name, tier, now
        )
    finally:
        await conn.close()


def _create_api_key_sqlite(key_hash, prefix, email, name, tier, now):
    import sqlite3
    conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
    conn.execute("INSERT INTO api_keys (key_hash,key_prefix,email,name,tier,created_at) VALUES (?,?,?,?,?,?)",
                 (key_hash, prefix, email, name, tier, now))
    conn.commit()
    conn.close()


def validate_api_key(raw_key: str):
    if not raw_key or not raw_key.startswith("og_"):
        return None
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    if DATABASE_URL:
        return _run(_validate_api_key_pg(key_hash, now))
    return _validate_api_key_sqlite(key_hash, now)


async def _validate_api_key_pg(key_hash, now):
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM api_keys WHERE key_hash = $1", key_hash)
        if not row:
            return None
        await conn.execute(
            "UPDATE api_keys SET requests_today=requests_today+1, requests_total=requests_total+1, last_used=$1 WHERE key_hash=$2",
            now, key_hash
        )
        return dict(row)
    finally:
        await conn.close()


def _validate_api_key_sqlite(key_hash, now):
    import sqlite3
    conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("UPDATE api_keys SET requests_today=requests_today+1, requests_total=requests_total+1, last_used=? WHERE key_hash=?",
                 (now, key_hash))
    conn.commit()
    result = dict(row)
    conn.close()
    return result


def get_rate_limit(tier: str) -> int:
    return {"free": 50, "hobbyist": 500, "commercial": 5000}.get(tier, 50)


# ── Subscriptions ─────────────────────────────────────────────────────────────

def create_subscription(api_key_hash, email, norad_id, satellite_name,
                         lat, lon, elevation_m=0.0, min_score=60, alert_hours_ahead=2):
    now = datetime.now(timezone.utc).isoformat()
    if DATABASE_URL:
        return _run(_create_sub_pg(api_key_hash, email, norad_id, satellite_name,
                                    lat, lon, elevation_m, min_score, alert_hours_ahead, now))
    return _create_sub_sqlite(api_key_hash, email, norad_id, satellite_name,
                               lat, lon, elevation_m, min_score, alert_hours_ahead, now)


async def _create_sub_pg(api_key_hash, email, norad_id, satellite_name,
                          lat, lon, elevation_m, min_score, alert_hours_ahead, now):
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("""
            INSERT INTO alert_subscriptions
            (api_key_hash,email,norad_id,satellite_name,lat,lon,elevation_m,min_score,alert_hours_ahead,created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id
        """, api_key_hash, email, norad_id, satellite_name, lat, lon,
             elevation_m, min_score, alert_hours_ahead, now)
        return row["id"]
    finally:
        await conn.close()


def _create_sub_sqlite(api_key_hash, email, norad_id, satellite_name,
                        lat, lon, elevation_m, min_score, alert_hours_ahead, now):
    import sqlite3
    conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
    cur = conn.execute("""
        INSERT INTO alert_subscriptions
        (api_key_hash,email,norad_id,satellite_name,lat,lon,elevation_m,min_score,alert_hours_ahead,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (api_key_hash, email, norad_id, satellite_name, lat, lon,
          elevation_m, min_score, alert_hours_ahead, now))
    conn.commit()
    sub_id = cur.lastrowid
    conn.close()
    return sub_id


def get_active_subscriptions():
    if DATABASE_URL:
        return _run(_get_subs_pg())
    return _get_subs_sqlite()


async def _get_subs_pg():
    conn = await _get_conn()
    try:
        rows = await conn.fetch("SELECT * FROM alert_subscriptions WHERE active = 1")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def _get_subs_sqlite():
    import sqlite3
    conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM alert_subscriptions WHERE active = 1").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_alerted(subscription_id, pass_aos, score, grade):
    now = datetime.now(timezone.utc).isoformat()
    if DATABASE_URL:
        _run(_mark_alerted_pg(subscription_id, pass_aos, score, grade, now))
    else:
        _mark_alerted_sqlite(subscription_id, pass_aos, score, grade, now)


async def _mark_alerted_pg(sub_id, pass_aos, score, grade, now):
    conn = await _get_conn()
    try:
        await conn.execute("UPDATE alert_subscriptions SET last_alerted=$1 WHERE id=$2", now, sub_id)
        await conn.execute("INSERT INTO alert_log (subscription_id,pass_aos,score,grade,sent_at) VALUES ($1,$2,$3,$4,$5)",
                           sub_id, pass_aos, score, grade, now)
    finally:
        await conn.close()


def _mark_alerted_sqlite(sub_id, pass_aos, score, grade, now):
    import sqlite3
    conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
    conn.execute("UPDATE alert_subscriptions SET last_alerted=? WHERE id=?", (now, sub_id))
    conn.execute("INSERT INTO alert_log (subscription_id,pass_aos,score,grade,sent_at) VALUES (?,?,?,?,?)",
                 (sub_id, pass_aos, score, grade, now))
    conn.commit()
    conn.close()


def delete_subscription(subscription_id, api_key_hash):
    if DATABASE_URL:
        return _run(_delete_sub_pg(subscription_id, api_key_hash))
    return _delete_sub_sqlite(subscription_id, api_key_hash)


async def _delete_sub_pg(sub_id, api_key_hash):
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM alert_subscriptions WHERE id=$1 AND api_key_hash=$2", sub_id, api_key_hash)
        return result != "DELETE 0"
    finally:
        await conn.close()


def _delete_sub_sqlite(sub_id, api_key_hash):
    import sqlite3
    conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
    cur = conn.execute("DELETE FROM alert_subscriptions WHERE id=? AND api_key_hash=?", (sub_id, api_key_hash))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def get_conn_for_admin():
    return DATABASE_URL
