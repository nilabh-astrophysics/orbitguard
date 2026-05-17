"""
OrbitGuard API v2
- API key authentication
- Email alerts via Resend
- IONEX ionospheric TEC scoring layer
- SQLite persistence
- Space-Track satellite search
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
    create_subscription, get_active_subscriptions, delete_subscription
)
from alerts import alert_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me-in-production")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(alert_scheduler())
    logger.info("OrbitGuard v2 started")
    yield


app = FastAPI(
    title="OrbitGuard API",
    description="Satellite pass quality forecasting — orbital geometry + space weather + ionospheric scoring.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://orbitguard-1.onrender.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_api_key_record(x_api_key: str = None):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required. Pass X-Api-Key header.")
    record = validate_api_key(x_api_key)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    if record["requests_today"] > get_rate_limit(record["tier"]):
        raise HTTPException(status_code=429, detail=f"Daily rate limit reached for {record['tier']} tier.")
    return record


@app.get("/")
def root():
    return {"service": "OrbitGuard", "version": "0.2.0", "status": "online", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/keys/register")
def register(email: str = Query(...), name: str = Query(None)):
    raw_key = create_api_key(email=email, name=name, tier="free")
    return {
        "api_key": raw_key,
        "tier": "free",
        "daily_limit": 50,
        "message": "Save this key — it won't be shown again. Pass it as X-Api-Key header.",
    }


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
    logger.info(f"Pass request: NORAD {norad_id}, lat={lat}, lon={lon} [{key['email']}]")
    orbital = passes_from_norad(norad_id, lat, lon, elevation_m, min_elevation_deg, hours_ahead)
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
    }


@app.post("/passes/tle")
async def passes_by_tle(body: dict, x_api_key: str = Header(None)):
    get_api_key_record(x_api_key)
    passes = compute_passes(
        tle_name=body.get("satellite_name", "UNKNOWN"),
        tle_line1=body["tle_line1"],
        tle_line2=body["tle_line2"],
        lat=body["lat"], lon=body["lon"],
        elevation_m=body.get("elevation_m", 0.0),
        min_elevation_deg=body.get("min_elevation_deg", 10.0),
        hours_ahead=body.get("hours_ahead", 48),
    )
    weather = get_space_weather_snapshot()
    tec_data = fetch_tec(body["lat"], body["lon"])
    scored_passes = score_pass_list(passes, weather, tec_data)
    return {
        "satellite_name": body.get("satellite_name", "UNKNOWN"),
        "ground_station": {"lat": body["lat"], "lon": body["lon"]},
        "pass_count": len(scored_passes),
        "space_weather": weather,
        "ionospheric": tec_data,
        "passes": scored_passes,
    }


@app.get("/satellites/search")
def search_sats(
    q: str = Query(..., description="Satellite name to search"),
    x_api_key: str = Header(None),
):
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
            {"name": "STARLINK-1007", "norad_id": 44713},
            {"name": "CUTE", "norad_id": 49263},
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
        {"name": "STARLINK-1007", "norad_id": 44713, "type": "Comms"},
        {"name": "CUTE (CubeSat)", "norad_id": 49263, "type": "CubeSat"},
    ]}


@app.post("/alerts/subscribe")
def subscribe_alert(
    norad_id: int = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
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
    return {
        "subscription_id": sub_id,
        "satellite": sat_name,
        "norad_id": norad_id,
        "alert_email": key["email"],
        "min_score": min_score,
        "alert_hours_ahead": alert_hours_ahead,
        "message": f"Alert active. You'll be emailed when {sat_name} scores {min_score}+ within {alert_hours_ahead}h.",
    }


@app.delete("/alerts/{subscription_id}")
def unsubscribe_alert(subscription_id: int, x_api_key: str = Header(None)):
    key = get_api_key_record(x_api_key)
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    deleted = delete_subscription(subscription_id, key_hash)
    if not deleted:
        raise HTTPException(status_code=404, detail="Subscription not found or not yours.")
    return {"message": f"Subscription {subscription_id} deleted."}


@app.get("/alerts/my")
def my_subscriptions(x_api_key: str = Header(None)):
    key = get_api_key_record(x_api_key)
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    all_subs = get_active_subscriptions()
    mine = [s for s in all_subs if s["api_key_hash"] == key_hash]
    return {"subscriptions": mine, "count": len(mine)}


@app.get("/admin/keys")
def admin_list_keys(secret: str = Query(...)):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    from database import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key_prefix, email, name, tier, requests_today, requests_total, created_at FROM api_keys"
        ).fetchall()
    return {"keys": [dict(r) for r in rows], "count": len(rows)}


@app.post("/admin/keys/grant")
def admin_grant_key(
    email: str = Query(...),
    tier: str = Query("hobbyist"),
    secret: str = Query(...),
):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    raw_key = create_api_key(email=email, tier=tier)
    return {"api_key": raw_key, "tier": tier, "email": email}
