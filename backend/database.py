"""
OrbitGuard Database v3
- Trial expiry: 14 days from key creation
- After expiry, all API calls blocked until manually extended
"""

import os
import secrets
import hashlib
import logging
import requests as req
from datetime import datetime, timezone, date, timedelta

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
DB_PATH = os.environ.get("DB_PATH", "./orbitguard.db")
CONTACT_EMAIL = "nilabhkalita47095@gmail.com"
TRIAL_DAYS = 14


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
        logger.info("Using Supabase REST API")
        _ensure_supabase_tables()
    else:
        _init_sqlite()


def _ensure_supabase_tables():
    for table in ["api_keys", "alert_subscriptions", "alert_log"]:
        try:
            r = req.get(_sb(f"/{table}?limit=1"), headers=_headers(), timeout=5)
            if r.status_code == 404:
                logger.error(f"Table '{table}' missing in Supabase")
        except Exception as e:
            logger.warning(f"Supabase check failed: {e}")


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
            tier TEXT DEFAULT 'trial',
            requests_today INTEGER DEFAULT 0,
            requests_total INTEGER DEFAULT 0,
            last_used TEXT,
            last_reset_date TEXT,
            trial_expires_at TEXT,
            is_active INTEGER DEFAULT 1,
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
    logger.info("SQLite initialized")


def generate_api_key():
    raw = "og_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


def create_api_key(email: str, name: str = None, tier: str = "trial",
                   trial_days: int = TRIAL_DAYS) -> str:
    raw, key_hash = generate_api_key()
    prefix = raw[:10]
    now = datetime.now(timezone.utc)
    trial_expires = (now + timedelta(days=trial_days)).isoformat()
    record = {
        "key_hash": key_hash,
        "key_prefix": prefix,
        "email": email,
        "name": name,
        "tier": tier,
        "created_at": now.isoformat(),
        "last_reset_date": date.today().isoformat(),
        "trial_expires_at": trial_expires,
        "is_active": 1,
        "requests_today": 0,
        "requests_total": 0,
    }
    if _use_supabase():
        r = req.post(_sb("/api_keys"), json=record, headers=_headers(), timeout=10)
        if r.status_code not in (200, 201):
            raise Exception(f"Supabase insert failed: {r.text}")
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO api_keys
            (key_hash,key_prefix,email,name,tier,created_at,last_reset_date,trial_expires_at,is_active)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (key_hash, prefix, email, name, tier,
              now.isoformat(), date.today().isoformat(), trial_expires, 1))
        conn.commit()
        conn.close()
    return raw


def check_trial_status(record: dict) -> dict:
    """
    Returns dict with:
      - expired: bool
      - days_remaining: int
      - message: str shown to user if expired
    """
    tier = record.get("tier", "trial")
    is_active = record.get("is_active", 1)

    # Manually deactivated
    if not is_active:
        return {
            "expired": True,
            "days_remaining": 0,
            "message": (
                f"Your OrbitGuard access has been deactivated. "
                f"Contact {CONTACT_EMAIL} to discuss access options."
            )
        }

    # Paid tiers never expire
    if tier in ("hobbyist", "commercial", "unlimited"):
        return {"expired": False, "days_remaining": 99999, "message": ""}

    # Check trial expiry
    trial_expires_at = record.get("trial_expires_at")
    if not trial_expires_at:
        return {"expired": False, "days_remaining": TRIAL_DAYS, "message": ""}

    try:
        expires = datetime.fromisoformat(trial_expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        remaining = (expires - now).days

        if now > expires:
            return {
                "expired": True,
                "days_remaining": 0,
                "message": (
                    f"Your 14-day OrbitGuard trial has ended. "
                    f"To continue using OrbitGuard, contact {CONTACT_EMAIL}. "
                    f"Reply with your use case and we'll discuss the right plan for you."
                )
            }
        return {"expired": False, "days_remaining": max(0, remaining), "message": ""}
    except Exception:
        return {"expired": False, "days_remaining": TRIAL_DAYS, "message": ""}


def validate_api_key(raw_key: str):
    if not raw_key or not raw_key.startswith("og_"):
        return None
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()

    if _use_supabase():
        r = req.get(_sb(f"/api_keys?key_hash=eq.{key_hash}"),
                    headers=_headers(), timeout=10)
        if r.status_code != 200 or not r.json():
            return None
        record = r.json()[0]
        needs_reset = record.get("last_reset_date") != today
        update = {
            "requests_today": 1 if needs_reset else record["requests_today"] + 1,
            "requests_total": record["requests_total"] + 1,
            "last_used": now,
        }
        if needs_reset:
            update["last_reset_date"] = today
        req.patch(_sb(f"/api_keys?key_hash=eq.{key_hash}"),
                  json=update, headers=_headers(), timeout=10)
        record.update(update)
        return record
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM api_keys WHERE key_hash=?",
                           (key_hash,)).fetchone()
        if not row:
            conn.close()
            return None
        result = dict(row)
        needs_reset = result.get("last_reset_date") != today
        new_today = 1 if needs_reset else result["requests_today"] + 1
        conn.execute("""
            UPDATE api_keys
            SET requests_today=?, requests_total=requests_total+1,
                last_used=?, last_reset_date=?
            WHERE key_hash=?
        """, (new_today, now, today, key_hash))
        conn.commit()
        conn.close()
        result["requests_today"] = new_today
        return result


def get_rate_limit(tier: str) -> int:
    return {
        "trial": 200,
        "free": 100,
        "hobbyist": 1000,
        "commercial": 10000,
        "unlimited": 999999,
    }.get(tier, 100)


def extend_trial(raw_key: str, extra_days: int) -> bool:
    """Extend a key's trial by N days from today."""
    if not raw_key.startswith("og_"):
        return False
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    new_expiry = (datetime.now(timezone.utc) + timedelta(days=extra_days)).isoformat()
    if _use_supabase():
        r = req.patch(_sb(f"/api_keys?key_hash=eq.{key_hash}"),
                      json={"trial_expires_at": new_expiry, "is_active": 1},
                      headers=_headers(), timeout=10)
        return r.status_code in (200, 204)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "UPDATE api_keys SET trial_expires_at=?, is_active=1 WHERE key_hash=?",
            (new_expiry, key_hash))
        conn.commit()
        conn.close()
        return cur.rowcount > 0


def upgrade_api_key(raw_key: str, new_tier: str) -> bool:
    """Upgrade tier — removes trial expiry."""
    if not raw_key.startswith("og_"):
        return False
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    # Set trial_expires_at far future when upgrading to paid
    far_future = (datetime.now(timezone.utc) + timedelta(days=36500)).isoformat()
    update = {"tier": new_tier, "trial_expires_at": far_future, "is_active": 1}
    if _use_supabase():
        r = req.patch(_sb(f"/api_keys?key_hash=eq.{key_hash}"),
                      json=update, headers=_headers(), timeout=10)
        return r.status_code in (200, 204)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "UPDATE api_keys SET tier=?, trial_expires_at=?, is_active=1 WHERE key_hash=?",
            (new_tier, far_future, key_hash))
        conn.commit()
        conn.close()
        return cur.rowcount > 0


def deactivate_key(raw_key: str) -> bool:
    """Hard-block a key immediately."""
    if not raw_key.startswith("og_"):
        return False
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    if _use_supabase():
        r = req.patch(_sb(f"/api_keys?key_hash=eq.{key_hash}"),
                      json={"is_active": 0}, headers=_headers(), timeout=10)
        return r.status_code in (200, 204)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "UPDATE api_keys SET is_active=0 WHERE key_hash=?", (key_hash,))
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
        r = req.post(_sb("/alert_subscriptions"), json=record,
                     headers=_headers(), timeout=10)
        if r.status_code in (200, 201):
            return r.json()[0]["id"]
        raise Exception(f"Insert failed: {r.text}")
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""
            INSERT INTO alert_subscriptions
            (api_key_hash,email,norad_id,satellite_name,lat,lon,
             elevation_m,min_score,alert_hours_ahead,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (api_key_hash, email, norad_id, satellite_name, lat, lon,
              elevation_m, min_score, alert_hours_ahead, now))
        conn.commit()
        sub_id = cur.lastrowid
        conn.close()
        return sub_id


def get_active_subscriptions():
    if _use_supabase():
        r = req.get(_sb("/alert_subscriptions?active=eq.1"),
                    headers=_headers(), timeout=10)
        return r.json() if r.status_code == 200 else []
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM alert_subscriptions WHERE active=1").fetchall()
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
        conn.execute("UPDATE alert_subscriptions SET last_alerted=? WHERE id=?",
                     (now, subscription_id))
        conn.execute("""INSERT INTO alert_log
            (subscription_id,pass_aos,score,grade,sent_at) VALUES (?,?,?,?,?)""",
                     (subscription_id, pass_aos, score, grade, now))
        conn.commit()
        conn.close()


def delete_subscription(subscription_id, api_key_hash):
    if _use_supabase():
        r = req.delete(
            _sb(f"/alert_subscriptions?id=eq.{subscription_id}&api_key_hash=eq.{api_key_hash}"),
            headers=_headers(), timeout=10)
        return r.status_code in (200, 204)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "DELETE FROM alert_subscriptions WHERE id=? AND api_key_hash=?",
            (subscription_id, api_key_hash))
        conn.commit()
        conn.close()
        return cur.rowcount > 0
