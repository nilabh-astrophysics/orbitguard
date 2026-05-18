"""
OrbitGuard Database — Postgres via Supabase
Uses psycopg2 for all storage. Falls back to SQLite if DATABASE_URL not set.
"""

import os
import secrets
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn, "postgres"
    else:
        import sqlite3
        conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
        conn.row_factory = sqlite3.Row
        return conn, "sqlite"


def init_db():
    conn, db_type = get_conn()
    try:
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute("""
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
            cur.execute("""
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alert_log (
                    id SERIAL PRIMARY KEY,
                    subscription_id INTEGER NOT NULL,
                    pass_aos TEXT NOT NULL,
                    score REAL NOT NULL,
                    grade TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                )
            """)
        else:
            cur.executescript("""
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
        logger.info(f"Database initialized ({db_type})")
    finally:
        conn.close()


def _row_to_dict(row, cursor=None, db_type="sqlite"):
    if db_type == "postgres" and cursor:
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    return dict(row)


def generate_api_key():
    raw = "og_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


def create_api_key(email: str, name: str = None, tier: str = "free") -> str:
    raw, key_hash = generate_api_key()
    prefix = raw[:10]
    now = datetime.now(timezone.utc).isoformat()
    conn, db_type = get_conn()
    try:
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute(
                "INSERT INTO api_keys (key_hash, key_prefix, email, name, tier, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (key_hash, prefix, email, name, tier, now)
            )
        else:
            cur.execute(
                "INSERT INTO api_keys (key_hash, key_prefix, email, name, tier, created_at) VALUES (?,?,?,?,?,?)",
                (key_hash, prefix, email, name, tier, now)
            )
        conn.commit()
    finally:
        conn.close()
    return raw


def validate_api_key(raw_key: str):
    if not raw_key or not raw_key.startswith("og_"):
        return None
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    conn, db_type = get_conn()
    try:
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute("SELECT * FROM api_keys WHERE key_hash = %s", (key_hash,))
            row = cur.fetchone()
            if not row:
                return None
            result = _row_to_dict(row, cur, "postgres")
            cur.execute(
                "UPDATE api_keys SET requests_today = requests_today + 1, requests_total = requests_total + 1, last_used = %s WHERE key_hash = %s",
                (now, key_hash)
            )
        else:
            cur.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,))
            row = cur.fetchone()
            if not row:
                return None
            result = dict(row)
            cur.execute(
                "UPDATE api_keys SET requests_today = requests_today + 1, requests_total = requests_total + 1, last_used = ? WHERE key_hash = ?",
                (now, key_hash)
            )
        conn.commit()
        return result
    finally:
        conn.close()


def get_rate_limit(tier: str) -> int:
    return {"free": 50, "hobbyist": 500, "commercial": 5000}.get(tier, 50)


def create_subscription(api_key_hash, email, norad_id, satellite_name,
                         lat, lon, elevation_m=0.0, min_score=60, alert_hours_ahead=2):
    now = datetime.now(timezone.utc).isoformat()
    conn, db_type = get_conn()
    try:
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute("""
                INSERT INTO alert_subscriptions
                (api_key_hash,email,norad_id,satellite_name,lat,lon,elevation_m,min_score,alert_hours_ahead,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (api_key_hash, email, norad_id, satellite_name, lat, lon, elevation_m, min_score, alert_hours_ahead, now))
            sub_id = cur.fetchone()[0]
        else:
            cur.execute("""
                INSERT INTO alert_subscriptions
                (api_key_hash,email,norad_id,satellite_name,lat,lon,elevation_m,min_score,alert_hours_ahead,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (api_key_hash, email, norad_id, satellite_name, lat, lon, elevation_m, min_score, alert_hours_ahead, now))
            sub_id = cur.lastrowid
        conn.commit()
        return sub_id
    finally:
        conn.close()


def get_active_subscriptions():
    conn, db_type = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM alert_subscriptions WHERE active = 1")
        rows = cur.fetchall()
        if db_type == "postgres":
            return [_row_to_dict(r, cur, "postgres") for r in rows]
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_alerted(subscription_id, pass_aos, score, grade):
    now = datetime.now(timezone.utc).isoformat()
    conn, db_type = get_conn()
    try:
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute("UPDATE alert_subscriptions SET last_alerted = %s WHERE id = %s", (now, subscription_id))
            cur.execute("INSERT INTO alert_log (subscription_id,pass_aos,score,grade,sent_at) VALUES (%s,%s,%s,%s,%s)",
                        (subscription_id, pass_aos, score, grade, now))
        else:
            cur.execute("UPDATE alert_subscriptions SET last_alerted = ? WHERE id = ?", (now, subscription_id))
            cur.execute("INSERT INTO alert_log (subscription_id,pass_aos,score,grade,sent_at) VALUES (?,?,?,?,?)",
                        (subscription_id, pass_aos, score, grade, now))
        conn.commit()
    finally:
        conn.close()


def delete_subscription(subscription_id, api_key_hash):
    conn, db_type = get_conn()
    try:
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute("DELETE FROM alert_subscriptions WHERE id = %s AND api_key_hash = %s",
                        (subscription_id, api_key_hash))
        else:
            cur.execute("DELETE FROM alert_subscriptions WHERE id = ? AND api_key_hash = ?",
                        (subscription_id, api_key_hash))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_conn_for_admin():
    return get_conn()
