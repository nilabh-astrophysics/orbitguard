"""
OrbitGuard API v2.2
- 14-day trial enforcement
- Trial extension + hard deactivation via admin
- Correct severity labels
"""

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
import hashlib
import os

from orbital import passes_from_norad, compute_passes, search_satellites
from space_weather import get_space_weather_snapshot
from scoring import score_pass_list
from ionex import fetch_tec
from database import (
    init_db, create_api_key, validate_api_key, get_rate_limit,
    check_trial_status, extend_trial, upgrade_api_key, deactivate_key,
    create_subscription, get_active_subscriptions, delete_subscription,
)
from alerts import alert_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me-in-production")
CONTACT_EMAIL = "nilabhkalita47095@gmail.com"
TIER_LIMITS = {"trial": 200, "free": 100, "hobbyist": 1000,
               "commercial": 10000, "unlimited": 999999}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(alert_scheduler())
    logger.info("OrbitGuard v2.2 started")
    yield


app = FastAPI(
    title="OrbitGuard API",
    description="Satellite pass quality forecasting.",
    version="0.2.2",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://orbitguard-1.onrender.com", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_api_key_record(x_api_key: str = None):
    if not x_api_key:
        raise HTTPException(status_code=401,
            detail="API key required. Pass X-Api-Key header.")
    record = validate_api_key(x_api_key)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    # Trial / expiry check
    trial = check_trial_status(record)
    if trial["expired"]:
        raise HTTPException(status_code=403, detail={
            "error": "trial_expired",
            "message": trial["message"],
            "contact": CONTACT_EMAIL,
        })

    # Rate limit check
    limit = get_rate_limit(record["tier"])
    if record["requests_today"] > limit:
        raise HTTPException(status_code=429, detail={
            "error": "rate_limit_exceeded",
            "message": f"Daily limit of {limit} requests reached for {record['tier']} tier. Resets at UTC midnight.",
            "tier": record["tier"],
            "limit": limit,
            "used": record["requests_today"],
            "contact": CONTACT_EMAIL,
        })

    # Attach trial info to record for response headers
    record["_trial_days_remaining"] = trial["days_remaining"]
    return record


# ── Public routes ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"service": "OrbitGuard", "version": "0.2.2",
            "status": "online", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/keys/register")
def register(email: str = Query(...), name: str = Query(None)):
    raw_key = create_api_key(email=email, name=name, tier="trial")
    return {
        "api_key": raw_key,
        "tier": "trial",
        "trial_days": 14,
        "daily_limit": TIER_LIMITS["trial"],
        "message": (
            "14-day trial activated. Save this key — shown once only. "
            f"After trial ends, contact {CONTACT_EMAIL} to continue."
        ),
    }


# ── Authenticated routes ──────────────────────────────────────────────────────

@app.get("/space-weather")
def space_weather(x_api_key: str = Header(None)):
    get_api_key_record(x_api_key)
    return get_space_weather_snapshot()


@app.get("/passes/norad/{norad_id}")
def passes_by_norad(
    norad_id: int,
    lat: float = Query(...),
    lon: float = Query(...),
    elevation_m: float = Query(0.0),
    min_elevation_deg: float = Query(10.0),
    hours_ahead: int = Query(48),
    include_ionex: bool = Query(True),
    x_api_key: str = Header(None),
):
    key = get_api_key_record(x_api_key)
    logger.info(f"Pass request: NORAD {norad_id} [{key['email']}]")

    orbital = passes_from_norad(norad_id, lat, lon, elevation_m,
                                min_elevation_deg, hours_ahead)
    if "error" in orbital:
        raise HTTPException(status_code=404, detail=orbital["error"])

    weather = get_space_weather_snapshot()
    tec_data = fetch_tec(lat, lon) if include_ionex else None
    scored_passes = score_pass_list(orbital["passes"], weather, tec_data)

    return {
        "satellite_name": orbital["satellite_name"],
        "norad_id": norad_id,
        "ground_station": orbital["ground_station"],
        "forecast_hours": hours_ahead,
        "pass_count": len(scored_passes),
        "space_weather": weather,
        "ionospheric": tec_data,
        "passes": scored_passes,
        "trial": {
            "days_remaining": key["_trial_days_remaining"],
            "tier": key["tier"],
            "requests_today": key["requests_today"],
            "daily_limit": get_rate_limit(key["tier"]),
        },
    }


@app.post("/passes/tle")
async def passes_by_tle(body: dict, x_api_key: str = Header(None)):
    get_api_key_record(x_api_key)
    passes = compute_passes(
        tle_name=body.get("satellite_name", "UNKNOWN"),
        tle_line1=body["tle_line1"], tle_line2=body["tle_line2"],
        lat=body["lat"], lon=body["lon"],
        elevation_m=body.get("elevation_m", 0.0),
        min_elevation_deg=body.get("min_elevation_deg", 10.0),
        hours_ahead=body.get("hours_ahead", 48),
    )
    weather = get_space_weather_snapshot()
    tec_data = fetch_tec(body["lat"], body["lon"])
    scored = score_pass_list(passes, weather, tec_data)
    return {
        "satellite_name": body.get("satellite_name", "UNKNOWN"),
        "ground_station": {"lat": body["lat"], "lon": body["lon"]},
        "pass_count": len(scored),
        "space_weather": weather,
        "ionospheric": tec_data,
        "passes": scored,
    }


@app.get("/satellites/search")
def search_sats(q: str = Query(...), x_api_key: str = Header(None)):
    get_api_key_record(x_api_key)
    results = search_satellites(q)
    if not results:
        popular = [
            {"name": "ISS (ZARYA)", "norad_id": 25544},
            {"name": "TERRA", "norad_id": 25994},
            {"name": "AQUA", "norad_id": 27424},
            {"name": "LANDSAT 9", "norad_id": 49260},
            {"name": "SENTINEL-2A", "norad_id": 40697},
            {"name": "NOAA 18", "norad_id": 28654},
            {"name": "NOAA-20", "norad_id": 43013},
            {"name": "CARTOSAT-3", "norad_id": 44857},
        ]
        results = [s for s in popular if q.upper() in s["name"].upper()]
    return {"results": results, "count": len(results)}


@app.get("/satellites/popular")
def popular_satellites():
    return {"satellites": [
        {"name": "ISS (ZARYA)", "norad_id": 25544, "type": "Space Station"},
        {"name": "TERRA", "norad_id": 25994, "type": "Earth Observation"},
        {"name": "AQUA", "norad_id": 27424, "type": "Earth Observation"},
        {"name": "LANDSAT 9", "norad_id": 49260, "type": "Earth Observation"},
        {"name": "SENTINEL-2A", "norad_id": 40697, "type": "Earth Observation"},
        {"name": "NOAA 18", "norad_id": 28654, "type": "Weather"},
        {"name": "NOAA-20", "norad_id": 43013, "type": "Weather"},
        {"name": "CARTOSAT-3", "norad_id": 44857, "type": "Earth Observation"},
    ]}


@app.get("/keys/status")
def key_status(x_api_key: str = Header(None)):
    """Check your trial status, usage, and limits."""
    key = get_api_key_record(x_api_key)
    return {
        "tier": key["tier"],
        "trial_days_remaining": key["_trial_days_remaining"],
        "trial_expires_at": key.get("trial_expires_at"),
        "requests_today": key["requests_today"],
        "daily_limit": get_rate_limit(key["tier"]),
        "remaining_today": max(0, get_rate_limit(key["tier"]) - key["requests_today"]),
        "contact_for_upgrade": CONTACT_EMAIL,
    }


@app.post("/alerts/subscribe")
def subscribe_alert(
    norad_id: int = Query(...),
    lat: float = Query(...), lon: float = Query(...),
    elevation_m: float = Query(0.0),
    min_score: int = Query(60),
    alert_hours_ahead: int = Query(2),
    x_api_key: str = Header(None),
):
    key = get_api_key_record(x_api_key)
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    from orbital import get_tle
    tle = get_tle(norad_id)
    sat_name = tle[0] if tle else f"NORAD-{norad_id}"
    sub_id = create_subscription(
        api_key_hash=key_hash, email=key["email"],
        norad_id=norad_id, satellite_name=sat_name,
        lat=lat, lon=lon, elevation_m=elevation_m,
        min_score=min_score, alert_hours_ahead=alert_hours_ahead,
    )
    return {"subscription_id": sub_id, "satellite": sat_name,
            "alert_email": key["email"], "min_score": min_score}


@app.delete("/alerts/{subscription_id}")
def unsubscribe(subscription_id: int, x_api_key: str = Header(None)):
    key = get_api_key_record(x_api_key)
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    if not delete_subscription(subscription_id, key_hash):
        raise HTTPException(status_code=404, detail="Subscription not found.")
    return {"message": f"Subscription {subscription_id} deleted."}


@app.get("/alerts/my")
def my_alerts(x_api_key: str = Header(None)):
    key = get_api_key_record(x_api_key)
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    all_subs = get_active_subscriptions()
    return {"subscriptions": [s for s in all_subs if s["api_key_hash"] == key_hash]}


# ── Admin routes ──────────────────────────────────────────────────────────────

def _check_admin(secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/admin/keys")
def admin_list(secret: str = Query(...)):
    _check_admin(secret)
    import requests as r2
    if _use_supabase():
        from database import _sb, _headers
        resp = r2.get(_sb("/api_keys?select=key_prefix,email,name,tier,requests_today,requests_total,trial_expires_at,is_active,created_at"),
                      headers=_headers(), timeout=10)
        rows = resp.json() if resp.status_code == 200 else []
    else:
        import sqlite3
        conn = sqlite3.connect(os.environ.get("DB_PATH", "./orbitguard.db"))
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT key_prefix,email,name,tier,requests_today,requests_total,trial_expires_at,is_active,created_at FROM api_keys"
        ).fetchall()]
        conn.close()
    return {"keys": rows, "count": len(rows)}


@app.post("/admin/keys/grant")
def admin_grant(email: str = Query(...), tier: str = Query("trial"),
                trial_days: int = Query(14), secret: str = Query(...)):
    _check_admin(secret)
    raw = create_api_key(email=email, tier=tier, trial_days=trial_days)
    return {"api_key": raw, "tier": tier, "trial_days": trial_days, "email": email}


@app.post("/admin/keys/extend")
def admin_extend(api_key: str = Query(...), extra_days: int = Query(14),
                 secret: str = Query(...)):
    """Extend a user's trial by N more days from today."""
    _check_admin(secret)
    success = extend_trial(api_key, extra_days)
    if not success:
        raise HTTPException(status_code=404, detail="Key not found.")
    return {"message": f"Trial extended by {extra_days} days.", "api_key_prefix": api_key[:10]}


@app.post("/admin/keys/upgrade")
def admin_upgrade(api_key: str = Query(...), tier: str = Query(...),
                  secret: str = Query(...)):
    """Upgrade to paid tier — removes expiry."""
    _check_admin(secret)
    if tier not in TIER_LIMITS:
        raise HTTPException(status_code=400,
            detail=f"Invalid tier. Choose: {list(TIER_LIMITS.keys())}")
    if not upgrade_api_key(api_key, tier):
        raise HTTPException(status_code=404, detail="Key not found.")
    return {"message": f"Upgraded to {tier}", "daily_limit": TIER_LIMITS[tier]}


@app.post("/admin/keys/deactivate")
def admin_deactivate(api_key: str = Query(...), secret: str = Query(...)):
    """Hard-block a key immediately."""
    _check_admin(secret)
    if not deactivate_key(api_key):
        raise HTTPException(status_code=404, detail="Key not found.")
    return {"message": "Key deactivated. User will see contact message on next request."}


def _use_supabase():
    from database import _use_supabase as _u
    return _u()
