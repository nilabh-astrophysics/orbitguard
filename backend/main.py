"""
OrbitGuard API — Satellite Pass Quality Forecasting
FastAPI backend serving pass windows + quality scores.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

class TLERequest(BaseModel):
    tle_line1: str
    tle_line2: str
    satellite_name: str = "UNKNOWN"
    lat: float
    lon: float
    elevation_m: float = 0.0
    min_elevation_deg: float = 10.0
    hours_ahead: int = 48

    model_config = {"json_schema_extra": {"example": {
        "tle_line1": "1 25544U 98067A   21275.56995718  .00002182  00000-0  47577-4 0  9998",
        "tle_line2": "2 25544  51.6461 339.4628 0003904 258.4779 244.6167 15.48834113305133",
        "satellite_name": "ISS (ZARYA)",
        "lat": 19.07, "lon": 72.87,
        "elevation_m": 0.0, "min_elevation_deg": 10.0, "hours_ahead": 48
    }}}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {"service": "OrbitGuard", "status": "online", "version": "0.1.0", "docs": "/docs"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


@app.get("/space-weather", tags=["Space Weather"])
def space_weather():
    return get_space_weather_snapshot()


@app.get("/passes/norad/{norad_id}", tags=["Passes"])
def passes_by_norad(
    norad_id: int,
    lat: float = Query(..., description="Ground station latitude"),
    lon: float = Query(..., description="Ground station longitude"),
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


@app.post("/passes/tle", tags=["Passes"])
def passes_by_tle(body: TLERequest):
    passes = compute_passes(
        tle_name=body.satellite_name,
        tle_line1=body.tle_line1,
        tle_line2=body.tle_line2,
        lat=body.lat, lon=body.lon,
        elevation_m=body.elevation_m,
        min_elevation_deg=body.min_elevation_deg,
        hours_ahead=body.hours_ahead,
    )
    weather = get_space_weather_snapshot()
    scored_passes = score_pass_list(passes, weather)
    return {
        "satellite_name": body.satellite_name,
        "ground_station": {"lat": body.lat, "lon": body.lon, "elevation_m": body.elevation_m},
        "forecast_hours": body.hours_ahead,
        "pass_count": len(scored_passes),
        "space_weather": weather,
        "passes": scored_passes,
    }


@app.get("/satellites/popular", tags=["Satellites"])
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
