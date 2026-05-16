"""
Orbital pass window calculator using Skyfield.
Given a TLE and ground station coordinates, returns upcoming pass windows.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import requests
from skyfield.api import load, wgs84, EarthSatellite
from skyfield.units import Angle

logger = logging.getLogger(__name__)

CELESTRAK_TLE_URL = "https://celestrak.org/SATCAT/TLE.PHP?CATNR={norad_id}"
CELESTRAK_GP_URL = "https://celestrak.org/SPACETRACK/query/class/gp/NORAD_CAT_ID/{norad_id}/FORMAT/TLE"

# Skyfield timescale (loaded once)
_ts = None


def get_timescale():
    global _ts
    if _ts is None:
        _ts = load.timescale()
    return _ts


def fetch_tle_from_celestrak(norad_id: int) -> Optional[tuple[str, str, str]]:
    """
    Fetch TLE from CelesTrak by NORAD catalog ID.
    Returns (name, line1, line2) or None on failure.
    """
    url = CELESTRAK_GP_URL.format(norad_id=norad_id)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
        if len(lines) >= 3:
            return lines[0], lines[1], lines[2]
        elif len(lines) == 2:
            return f"NORAD-{norad_id}", lines[0], lines[1]
        else:
            logger.error(f"Unexpected TLE format for {norad_id}: {lines}")
            return None
    except Exception as e:
        logger.error(f"CelesTrak fetch failed for {norad_id}: {e}")
        return None


def compute_passes(
    tle_name: str,
    tle_line1: str,
    tle_line2: str,
    lat: float,
    lon: float,
    elevation_m: float = 0.0,
    min_elevation_deg: float = 10.0,
    hours_ahead: int = 48,
    max_passes: int = 10,
) -> list[dict]:
    """
    Compute upcoming satellite pass windows over a ground station.

    Returns list of pass dicts with:
    - aos: acquisition of signal (UTC ISO)
    - los: loss of signal (UTC ISO)
    - max_elevation_deg: peak elevation angle
    - duration_seconds: pass duration
    - azimuth_at_max: azimuth at max elevation
    """
    ts = get_timescale()
    satellite = EarthSatellite(tle_line1, tle_line2, tle_name, ts)
    observer = wgs84.latlon(lat, lon, elevation_m=elevation_m)

    now = datetime.now(timezone.utc)
    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(now + timedelta(hours=hours_ahead))

    passes = []
    try:
        events_t, events_type = satellite.find_events(
            observer, t0, t1, altitude_degrees=min_elevation_deg
        )
    except Exception as e:
        logger.error(f"find_events failed: {e}")
        return []

    # Group events into passes: 0=rise, 1=culmination, 2=set
    i = 0
    while i < len(events_t) and len(passes) < max_passes:
        if events_type[i] == 0:  # AOS
            aos_t = events_t[i]
            peak_el = 0.0
            peak_az = 0.0
            los_t = None

            j = i + 1
            while j < len(events_t):
                if events_type[j] == 1:  # culmination
                    diff = satellite - observer
                    topocentric = diff.at(events_t[j])
                    alt, az, _ = topocentric.altaz()
                    peak_el = alt.degrees
                    peak_az = az.degrees
                elif events_type[j] == 2:  # LOS
                    los_t = events_t[j]
                    i = j
                    break
                j += 1

            if los_t is not None:
                aos_dt = aos_t.utc_datetime()
                los_dt = los_t.utc_datetime()
                duration = (los_dt - aos_dt).total_seconds()

                passes.append({
                    "aos": aos_dt.isoformat(),
                    "los": los_dt.isoformat(),
                    "max_elevation_deg": round(peak_el, 2),
                    "azimuth_at_max_deg": round(peak_az, 2),
                    "duration_seconds": round(duration),
                })
        i += 1

    return passes


def passes_from_norad(
    norad_id: int,
    lat: float,
    lon: float,
    elevation_m: float = 0.0,
    min_elevation_deg: float = 10.0,
    hours_ahead: int = 48,
) -> dict:
    """High-level: fetch TLE then compute passes. Returns full result dict."""
    tle = fetch_tle_from_celestrak(norad_id)
    if tle is None:
        return {
            "error": f"Could not fetch TLE for NORAD ID {norad_id}",
            "norad_id": norad_id,
        }

    name, line1, line2 = tle
    passes = compute_passes(
        name, line1, line2, lat, lon, elevation_m, min_elevation_deg, hours_ahead
    )

    return {
        "satellite_name": name,
        "norad_id": norad_id,
        "tle_line1": line1,
        "tle_line2": line2,
        "ground_station": {"lat": lat, "lon": lon, "elevation_m": elevation_m},
        "min_elevation_deg": min_elevation_deg,
        "hours_ahead": hours_ahead,
        "pass_count": len(passes),
        "passes": passes,
    }
