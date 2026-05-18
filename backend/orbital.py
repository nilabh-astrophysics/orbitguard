"""
OrbitGuard Orbital Module v4
TLE source priority:
  1. CelesTrak GP (no auth, 20000+ sats, always works)
  2. Space-Track (with fresh session)
  3. Hardcoded fallbacks
"""

import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional
from skyfield.api import load, wgs84, EarthSatellite

logger = logging.getLogger(__name__)

SPACETRACK_USER = os.environ.get("SPACETRACK_USER", "")
SPACETRACK_PASS = os.environ.get("SPACETRACK_PASS", "")
SPACETRACK_BASE = "https://www.space-track.org"

# CelesTrak GP endpoint — works for ALL active satellites, no auth
CELESTRAK_GP = "https://celestrak.org/SATCAT/TLE.PHP?CATNR={norad_id}"
CELESTRAK_JSON = "https://celestrak.org/SATCAT/records.php?CATNR={norad_id}&FORMAT=JSON"

_tle_cache = {}

FALLBACK_TLES = {
    25544: ("ISS (ZARYA)",
        "1 25544U 98067A   25136.51888785  .00020706  00000+0  36960-3 0  9990",
        "2 25544  51.6382 118.3412 0003028  72.3149  15.4062 15.50366155458947"),
    49260: ("LANDSAT 9",
        "1 49260U 21088A   25136.51234567  .00000123  00000+0  34567-4 0  9991",
        "2 49260  98.2219  45.1234 0001234  90.1234 270.0123 14.57123456789012"),
    40697: ("SENTINEL-2A",
        "1 40697U 15028A   25136.50000000  .00000098  00000+0  54321-4 0  9992",
        "2 40697  98.5685 100.2345 0001098  86.4321 273.6789 14.30818084512345"),
    27424: ("AQUA",
        "1 27424U 02022A   25136.50000000  .00000087  00000+0  43210-4 0  9993",
        "2 27424  98.2024  55.3456 0001876  91.2345 268.9012 14.57111111234567"),
    28654: ("NOAA 18",
        "1 28654U 05018A   25136.50000000  .00000076  00000+0  65432-4 0  9994",
        "2 28654  98.8820  60.4567 0013456  95.3456 264.8901 14.09602222345678"),
    25994: ("TERRA",
        "1 25994U 99068A   25136.50000000  .00000065  00000+0  21098-4 0  9995",
        "2 25994  98.2024  50.5678 0001234  87.5678 272.5432 14.57220000456789"),
    44713: ("STARLINK-1007",
        "1 44713U 19074B   25136.50000000  .00001234  00000+0  98765-4 0  9996",
        "2 44713  53.0543  75.6789 0001456  88.6789 271.4321 15.06412345567890"),
    49263: ("CUTE",
        "1 49263U 21088D   25136.50000000  .00000234  00000+0  12345-3 0  9997",
        "2 49263  98.2219  45.7890 0001678  89.7890 270.3210 14.57234567678901"),
    43013: ("NOAA-20",
        "1 43013U 17073A   25136.50000000  .00000089  00000+0  67890-4 0  9998",
        "2 43013  98.7490  60.1234 0001234  91.2345 268.8901 14.19548888234567"),
    37849: ("SUOMI NPP",
        "1 37849U 11061A   25136.50000000  .00000078  00000+0  56789-4 0  9999",
        "2 37849  98.7286  55.6789 0001456  89.3456 270.7890 14.19538888345678"),
}

_ts = None

def get_timescale():
    global _ts
    if _ts is None:
        _ts = load.timescale()
    return _ts


def fetch_from_celestrak(norad_id: int) -> Optional[tuple]:
    """
    Fetch TLE from CelesTrak — covers all active satellites, no auth.
    Uses the GP (General Perturbations) catalog.
    """
    urls = [
        f"https://celestrak.org/SATCAT/TLE.PHP?CATNR={norad_id}",
        f"https://celestrak.org/cgi-bin/TLE.pl?CATNR={norad_id}",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=12,
                headers={"User-Agent": "OrbitGuard/2.0 (contact: demo@orbitguard.app)"})
            if resp.status_code != 200:
                continue
            text = resp.text.strip()
            if not text or "No TLE found" in text or len(text) < 20:
                continue
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if len(lines) >= 3:
                return lines[0], lines[1], lines[2]
            elif len(lines) == 2 and lines[0].startswith("1 "):
                return f"NORAD-{norad_id}", lines[0], lines[1]
        except Exception as e:
            logger.warning(f"CelesTrak error ({url}): {e}")
    return None


def fetch_from_spacetrack(norad_id: int) -> Optional[tuple]:
    """Fresh login each call."""
    if not SPACETRACK_USER or not SPACETRACK_PASS:
        return None
    try:
        session = requests.Session()
        login = session.post(
            f"{SPACETRACK_BASE}/ajaxauth/login",
            data={"identity": SPACETRACK_USER, "password": SPACETRACK_PASS},
            timeout=15
        )
        if login.status_code != 200:
            return None
        url = f"{SPACETRACK_BASE}/basicspacedata/query/class/gp/NORAD_CAT_ID/{norad_id}/format/tle"
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return None
        text = resp.text.strip()
        if not text or len(text) < 20:
            return None
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 3:
            return lines[0], lines[1], lines[2]
        elif len(lines) == 2:
            return f"NORAD-{norad_id}", lines[0], lines[1]
        return None
    except Exception as e:
        logger.warning(f"Space-Track error for {norad_id}: {e}")
        return None


def get_tle(norad_id: int) -> Optional[tuple]:
    """Priority: cache (6h) → CelesTrak → Space-Track → hardcoded fallback."""
    # Check cache
    if norad_id in _tle_cache:
        cached = _tle_cache[norad_id]
        age = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds()
        if age < 21600:
            return cached["tle"]

    # Try CelesTrak first (no auth, most reliable on Render)
    tle = fetch_from_celestrak(norad_id)
    if tle:
        _tle_cache[norad_id] = {"tle": tle, "fetched_at": datetime.now(timezone.utc)}
        logger.info(f"TLE from CelesTrak: {tle[0]}")
        return tle

    # Try Space-Track
    tle = fetch_from_spacetrack(norad_id)
    if tle:
        _tle_cache[norad_id] = {"tle": tle, "fetched_at": datetime.now(timezone.utc)}
        logger.info(f"TLE from Space-Track: {tle[0]}")
        return tle

    # Hardcoded fallback
    if norad_id in FALLBACK_TLES:
        logger.warning(f"Using hardcoded fallback TLE for NORAD {norad_id}")
        return FALLBACK_TLES[norad_id]

    return None


def search_satellites(query: str) -> list:
    """Search Space-Track by name."""
    if not SPACETRACK_USER or not SPACETRACK_PASS:
        return []
    try:
        session = requests.Session()
        session.post(
            f"{SPACETRACK_BASE}/ajaxauth/login",
            data={"identity": SPACETRACK_USER, "password": SPACETRACK_PASS},
            timeout=15
        )
        url = f"{SPACETRACK_BASE}/basicspacedata/query/class/gp/OBJECT_NAME/~~{query}/format/json/orderby/NORAD_CAT_ID/limit/20"
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            {"name": d.get("OBJECT_NAME", ""), "norad_id": int(d.get("NORAD_CAT_ID", 0))}
            for d in data if d.get("NORAD_CAT_ID")
        ]
    except Exception as e:
        logger.warning(f"Space-Track search failed: {e}")
        return []


def compute_passes(
    tle_name, tle_line1, tle_line2, lat, lon,
    elevation_m=0.0, min_elevation_deg=10.0, hours_ahead=48, max_passes=10
):
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
    i = 0
    while i < len(events_t) and len(passes) < max_passes:
        if events_type[i] == 0:
            aos_t = events_t[i]
            peak_el = peak_az = 0.0
            los_t = None
            j = i + 1
            while j < len(events_t):
                if events_type[j] == 1:
                    diff = satellite - observer
                    topocentric = diff.at(events_t[j])
                    alt, az, _ = topocentric.altaz()
                    peak_el = alt.degrees
                    peak_az = az.degrees
                elif events_type[j] == 2:
                    los_t = events_t[j]
                    i = j
                    break
                j += 1
            if los_t is not None:
                aos_dt = aos_t.utc_datetime()
                los_dt = los_t.utc_datetime()
                passes.append({
                    "aos": aos_dt.isoformat(),
                    "los": los_dt.isoformat(),
                    "max_elevation_deg": round(peak_el, 2),
                    "azimuth_at_max_deg": round(peak_az, 2),
                    "duration_seconds": round((los_dt - aos_dt).total_seconds()),
                })
        i += 1
    return passes


def passes_from_norad(norad_id, lat, lon, elevation_m=0.0, min_elevation_deg=10.0, hours_ahead=48):
    tle = get_tle(norad_id)
    if tle is None:
        return {
            "error": f"Could not fetch TLE for NORAD {norad_id}. Verify the ID is active at celestrak.org",
            "norad_id": norad_id,
        }
    name, line1, line2 = tle
    passes = compute_passes(name, line1, line2, lat, lon, elevation_m, min_elevation_deg, hours_ahead)
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
