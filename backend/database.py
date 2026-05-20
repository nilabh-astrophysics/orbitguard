"""
OrbitGuard Database v2 — Supabase REST API
- Daily request counter auto-resets at UTC midnight
- Upgrade flow support
"""

import os
import secrets
import hashlib
import logging
import requests as req
from datetime import datetime, timezone, date

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
DB_PATH = os.environ.get("DB_PATH", "./orbitguard.db")


def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _use_supabase():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _sb(path):
    return f"{SUPABASE_URL}/rest/v1{path}"


def init_db():
    if _use_supabase():
        logger.info("Using Supabase REST API for storage")
        _ensure_supabase_tables()
    else:
        _init_sqlite()
        logger.info("Using SQLite for storage")


def _ensure_supabase_tables():
    for table in ["api_keys", "alert_subscriptions", "alert_log"]:
        try:
            r = req.get(_sb(f"/{table}?limit=1"), headers=_headers(), timeout=5)
            if r.status_code == 404:
                logger.error(f"Table '{table}' missing in Supabase")
        except Exception as e:
            logger.warning(f"Supabase table check failed: {e}")


def _init_sqlite():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
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
            last_reset_date TEXT,
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


def generate_api_key():
    raw = "og_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


def create_api_key(email: str, name: str = None, tier: str = "free") -> str:
    raw, key_hash = generate_api_key()
    prefix = raw[:10]
    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()
    record = {
        "key_hash": key_hash, "key_prefix": prefix, "email": email,
        "name": name, "tier": tier, "created_at": now,
        "last_reset_date": today, "requests_today": 0, "requests_total": 0,
    }
    if _use_supabase():
        r = req.post(_sb("/api_keys"), json=record, headers=_headers(), timeout=10)
        if r.status_code not in (200, 201):
            raise Exception(f"Supabase insert failed: {r.text}")
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO api_keys (key_hash,key_prefix,email,name,tier,created_at,last_reset_date) VALUES (?,?,?,?,?,?,?)",
            (key_hash, prefix, email, name, tier, now, today)
        )
        conn.commit()
        conn.close()
    return raw


def validate_api_key(raw_key: str):
    if not raw_key or not raw_key.startswith("og_"):
        return None
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()

    if _use_supabase():
        r = req.get(_sb(f"/api_keys?key_hash=eq.{key_hash}"), headers=_headers(), timeout=10)
        if r.status_code != 200 or not r.json():
            return None
        record = r.json()[0]

        # Reset daily counter if it's a new day
        needs_reset = record.get("last_reset_date") != today
        update = {
            "requests_today": 1 if needs_reset else record["requests_today"] + 1,
            "requests_total": record["requests_total"] + 1,
            "last_used": now,
        }
        if needs_reset:
            update["last_reset_date"] = today

        req.patch(
            _sb(f"/api_keys?key_hash=eq.{key_hash}"),
            json=update, headers=_headers(), timeout=10
        )
        record.update(update)
        return record
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM api_keys WHERE key_hash=?", (key_hash,)).fetchone()
        if not row:
            conn.close()
            return None
        result = dict(row)

        needs_reset = result.get("last_reset_date") != today
        new_today = 1 if needs_reset else result["requests_today"] + 1

        conn.execute(
            "UPDATE api_keys SET requests_today=?, requests_total=requests_total+1, last_used=?, last_reset_date=? WHERE key_hash=?",
            (new_today, now, today, key_hash)
        )
        conn.commit()
        conn.close()
        result["requests_today"] = new_today
        return result


def get_rate_limit(tier: str) -> int:
    return {"free": 100, "hobbyist": 1000, "commercial": 10000}.get(tier, 100)


def upgrade_api_key(raw_key: str, new_tier: str) -> bool:
    """Upgrade a key's tier. Called by admin endpoint."""
    if not raw_key.startswith("og_"):
        return False
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    if _use_supabase():
        r = req.patch(
            _sb(f"/api_keys?key_hash=eq.{key_hash}"),
            json={"tier": new_tier}, headers=_headers(), timeout=10
        )
        return r.status_code in (200, 204)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("UPDATE api_keys SET tier=? WHERE key_hash=?", (new_tier, key_hash))
        conn.commit()
        conn.close()
        return cur.rowcount > 0


def create_subscription(api_key_hash, email, norad_id, satellite_name,
                         lat, lon, elevation_m=0.0, min_score=60, alert_hours_ahead=2):
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "api_key_hash": api_key_hash, "email": email, "norad_id": norad_id,
        "satellite_name": satellite_name, "lat": lat, "lon": lon,
        "elevation_m": elevation_m, "min_score": min_score,
        "alert_hours_ahead": alert_hours_ahead, "created_at": now,
    }
    if _use_supabase():
        r = req.post(_sb("/alert_subscriptions"), json=record, headers=_headers(), timeout=10)
        if r.status_code in (200, 201):
            return r.json()[0]["id"]
        raise Exception(f"Supabase insert failed: {r.text}")
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""
            INSERT INTO alert_subscriptions
            (api_key_hash,email,norad_id,satellite_name,lat,lon,elevation_m,min_score,alert_hours_ahead,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (api_key_hash, email, norad_id, satellite_name, lat, lon,
             elevation_m, min_score, alert_hours_ahead, now))
        conn.commit()
        sub_id = cur.lastrowid
        conn.close()
        return sub_id


def get_active_subscriptions():
    if _use_supabase():
        r = req.get(_sb("/alert_subscriptions?active=eq.1"), headers=_headers(), timeout=10)
        return r.json() if r.status_code == 200 else []
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM alert_subscriptions WHERE active=1").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def mark_alerted(subscription_id, pass_aos, score, grade):
    now = datetime.now(timezone.utc).isoformat()
    if _use_supabase():
        req.patch(_sb(f"/alert_subscriptions?id=eq.{subscription_id}"),
                  json={"last_alerted": now}, headers=_headers(), timeout=10)
        req.post(_sb("/alert_log"),
                 json={"subscription_id": subscription_id, "pass_aos": pass_aos,
                       "score": score, "grade": grade, "sent_at": now},
                 headers=_headers(), timeout=10)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE alert_subscriptions SET last_alerted=? WHERE id=?", (now, subscription_id))
        conn.execute("INSERT INTO alert_log (subscription_id,pass_aos,score,grade,sent_at) VALUES (?,?,?,?,?)",
                     (subscription_id, pass_aos, score, grade, now))
        conn.commit()
        conn.close()


def delete_subscription(subscription_id, api_key_hash):
    if _use_supabase():
        r = req.delete(
            _sb(f"/alert_subscriptions?id=eq.{subscription_id}&api_key_hash=eq.{api_key_hash}"),
            headers=_headers(), timeout=10
        )
        return r.status_code in (200, 204)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("DELETE FROM alert_subscriptions WHERE id=? AND api_key_hash=?",
                           (subscription_id, api_key_hash))
        conn.commit()
        conn.close()
        return cur.rowcount > 0
