"""
OrbitGuard API — Satellite Pass Quality Forecasting
FastAPI backend serving pass windows + quality scores.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

class TLERequest(BaseModel):
    tle_line1: str = Field(..., description="TLE line 1")
    tle_line2: str = Field(..., description="TLE line 2")
    satellite_name: str = Field("UNKNOWN", description="Satellite name")
    lat: float = Field(..., ge=-90, le=90, description="Ground station latitude")
    lon: float = Field(..., ge=-180, le=180, description="Ground station longitude")
    elevation_m: float = Field(0.0, description="Ground station elevation in meters")
    min_elevation_deg: float = Field(10.0, ge=0, le=90, description="Minimum pass elevation angle")
    hours_ahead: int = Field(48, ge=1, le=168, description="Forecast horizon in hours")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "service": "OrbitGuard",
        "status": "online",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


@app.get("/space-weather", tags=["Space Weather"])
def space_weather():
    """
    Current space weather snapshot.
    Returns Kp index, F10.7 solar flux, active NOAA alerts, and severity classification.
    """
    return get_space_weather_snapshot()


@app.get("/passes/norad/{norad_id}", tags=["Passes"])
def passes_by_norad(
    norad_id: int,
    lat: float = Query(..., ge=-90, le=90, description="Ground station latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Ground station longitude"),
    elevation_m: float = Query(0.0, description="Ground station elevation (meters)"),
    min_elevation_deg: float = Query(10.0, ge=0, le=90),
    hours_ahead: int = Query(48, ge=1, le=168),
):
    """
    Fetch TLE from CelesTrak by NORAD ID, compute pass windows,
    and score each pass against current space weather.

    Example: NORAD 25544 = ISS, 44413 = STARLINK-1007
    """
    logger.info(f"Pass request: NORAD {norad_id}, lat={lat}, lon={lon}")

    # 1. Orbital passes
    orbital = passes_from_norad(
        norad_id, lat, lon, elevation_m, min_elevation_deg, hours_ahead
    )
    if "error" in orbital:
        raise HTTPException(status_code=404, detail=orbital["error"])

    # 2. Space weather
    weather = get_space_weather_snapshot()

    # 3. Score each pass
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


@app.post("/passes/tle", tags=["Passes"])
def passes_by_tle(body: TLERequest):
    """
    Compute pass windows from a raw TLE you provide (no NORAD lookup).
    Useful for satellites not yet in CelesTrak or custom TLEs.
    """
    passes = compute_passes(
        tle_name=body.satellite_name,
        tle_line1=body.tle_line1,
        tle_line2=body.tle_line2,
        lat=body.lat,
        lon=body.lon,
        elevation_m=body.elevation_m,
        min_elevation_deg=body.min_elevation_deg,
        hours_ahead=body.hours_ahead,
    )

    weather = get_space_weather_snapshot()
    scored_passes = score_pass_list(passes, weather)

    return {
        "satellite_name": body.satellite_name,
        "ground_station": {
            "lat": body.lat,
            "lon": body.lon,
            "elevation_m": body.elevation_m,
        },
        "forecast_hours": body.hours_ahead,
        "pass_count": len(scored_passes),
        "space_weather": weather,
        "passes": scored_passes,
    }


@app.get("/satellites/popular", tags=["Satellites"])
def popular_satellites():
    """Quick reference list of commonly tracked satellites with NORAD IDs."""
    return {
        "satellites": [
            {"name": "ISS (ZARYA)", "norad_id": 25544, "type": "Space Station"},
            {"name": "TERRA", "norad_id": 25994, "type": "Earth Observation"},
            {"name": "AQUA", "norad_id": 27424, "type": "Earth Observation"},
            {"name": "LANDSAT 9", "norad_id": 49260, "type": "Earth Observation"},
            {"name": "SENTINEL-2A", "norad_id": 40697, "type": "Earth Observation"},
            {"name": "NOAA 18", "norad_id": 28654, "type": "Weather"},
            {"name": "STARLINK-1007", "norad_id": 44713, "type": "Comms"},
            {"name": "CUTE (CubeSat)", "norad_id": 49263, "type": "CubeSat"},
        ]
    }
