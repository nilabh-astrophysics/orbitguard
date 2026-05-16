"""
OrbitGuard API — Satellite Pass Quality Forecasting
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import logging

from orbital import passes_from_norad, compute_passes
from space_weather import get_space_weather_snapshot
from scoring import score_pass_list

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OrbitGuard API",
    description="Satellite pass quality forecasting — orbital geometry + space weather scoring.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"service": "OrbitGuard", "status": "online", "version": "0.1.0", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/space-weather")
def space_weather():
    return get_space_weather_snapshot()


@app.get("/passes/norad/{norad_id}")
def passes_by_norad(
    norad_id: int,
    lat: float = Query(...),
    lon: float = Query(...),
    elevation_m: float = Query(0.0),
    min_elevation_deg: float = Query(10.0),
    hours_ahead: int = Query(48),
):
    logger.info(f"Pass request: NORAD {norad_id}, lat={lat}, lon={lon}")
    orbital = passes_from_norad(norad_id, lat, lon, elevation_m, min_elevation_deg, hours_ahead)
    if "error" in orbital:
        raise HTTPException(status_code=404, detail=orbital["error"])
    weather = get_space_weather_snapshot()
    scored_passes = score_pass_list(orbital["passes"], weather)
    return {
        "satellite_name": orbital["satellite_name"],
        "norad_id": norad_id,
        "ground_station": orbital["ground_station"],
        "forecast_hours": hours_ahead,
        "pass_count": len(scored_passes),
        "space_weather": weather,
        "passes": scored_passes,
    }


@app.post("/passes/tle")
async def passes_by_tle(body: dict):
    passes = compute_passes(
        tle_name=body.get("satellite_name", "UNKNOWN"),
        tle_line1=body["tle_line1"],
        tle_line2=body["tle_line2"],
        lat=body["lat"],
        lon=body["lon"],
        elevation_m=body.get("elevation_m", 0.0),
        min_elevation_deg=body.get("min_elevation_deg", 10.0),
        hours_ahead=body.get("hours_ahead", 48),
    )
    weather = get_space_weather_snapshot()
    scored_passes = score_pass_list(passes, weather)
    return {
        "satellite_name": body.get("satellite_name", "UNKNOWN"),
        "ground_station": {"lat": body["lat"], "lon": body["lon"], "elevation_m": body.get("elevation_m", 0.0)},
        "forecast_hours": body.get("hours_ahead", 48),
        "pass_count": len(scored_passes),
        "space_weather": weather,
        "passes": scored_passes,
    }


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
