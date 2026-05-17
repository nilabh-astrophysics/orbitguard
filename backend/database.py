"""
OrbitGuard Database
SQLite-backed storage for API keys and alert subscriptions.
File lives at /data/orbitguard.db on Render (persistent disk).
Falls back to local ./orbitguard.db for development.
"""

import sqlite3
import secrets
import hashlib
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Use /data/ on Render (mount a persistent disk there), local otherwise
DB_PATH = os.environ.get("DB_PATH", "./orbitguard.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
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
            created_at TEXT NOT NULL,
            FOREIGN KEY (api_key_hash) REFERENCES api_keys(key_hash)
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
    logger.info(f"Database initialized at {DB_PATH}")


# ── API Key management ────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key.
    Returns (raw_key, key_hash). Store hash, give user raw_key.
    Format: og_<32 random chars>
    """
    raw = "og_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


def create_api_key(email: str, name: str = None, tier: str = "free") -> str:
    """Create and store a new API key. Returns the raw key (shown once)."""
    raw, key_hash = generate_api_key()
    prefix = raw[:10]  # e.g. "og_abc123x" for display
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO api_keys (key_hash, key_prefix, email, name, tier, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key_hash, prefix, email, name, tier, now))
    logger.info(f"Created API key for {email} ({tier})")
    return raw


def validate_api_key(raw_key: str) -> dict | None:
    """
    Validate an API key. Returns key record or None if invalid.
    Also increments usage counters.
    """
    if not raw_key or not raw_key.startswith("og_"):
        return None
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        if not row:
            return None
        conn.execute("""
            UPDATE api_keys
            SET requests_today = requests_today + 1,
                requests_total = requests_total + 1,
                last_used = ?
            WHERE key_hash = ?
        """, (now, key_hash))
        return dict(row)


def get_rate_limit(tier: str) -> int:
    """Requests per day by tier."""
    limits = {"free": 50, "hobbyist": 500, "commercial": 5000}
    return limits.get(tier, 50)


# ── Alert subscriptions ───────────────────────────────────────────────────────

def create_subscription(
    api_key_hash: str,
    email: str,
    norad_id: int,
    satellite_name: str,
    lat: float,
    lon: float,
    elevation_m: float = 0.0,
    min_score: int = 60,
    alert_hours_ahead: int = 2,
) -> int:
    """Create an alert subscription. Returns subscription ID."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO alert_subscriptions
            (api_key_hash, email, norad_id, satellite_name, lat, lon,
             elevation_m, min_score, alert_hours_ahead, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (api_key_hash, email, norad_id, satellite_name, lat, lon,
              elevation_m, min_score, alert_hours_ahead, now))
        return cur.lastrowid


def get_active_subscriptions() -> list[dict]:
    """Get all active subscriptions for the alert scheduler."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_subscriptions WHERE active = 1"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_alerted(subscription_id: int, pass_aos: str, score: float, grade: str):
    """Record that an alert was sent for a specific pass."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            UPDATE alert_subscriptions SET last_alerted = ? WHERE id = ?
        """, (now, subscription_id))
        conn.execute("""
            INSERT INTO alert_log (subscription_id, pass_aos, score, grade, sent_at)
            VALUES (?, ?, ?, ?, ?)
        """, (subscription_id, pass_aos, score, grade, now))


def delete_subscription(subscription_id: int, api_key_hash: str) -> bool:
    """Delete a subscription (only if it belongs to this API key)."""
    with get_conn() as conn:
        cur = conn.execute("""
            DELETE FROM alert_subscriptions
            WHERE id = ? AND api_key_hash = ?
        """, (subscription_id, api_key_hash))
        return cur.rowcount > 0
