"""
IONEX Ionospheric TEC (Total Electron Content) Module
Fetches global ionospheric maps from NASA CDDIS / IGS.
Used to add ionospheric scintillation risk to pass scoring.

TEC unit: TECU (1 TECU = 10^16 electrons/m^2)
Typical values: 1-10 TECU quiet, 10-30 moderate, 30+ disturbed
"""

import requests
import logging
import os
import gzip
import io
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# IGS IONEX files via NASA CDDIS (requires Earthdata account) or JPL mirror
# We use the JPL IONEX which is publicly accessible
JPL_IONEX_URL = "https://sideshow.jpl.nasa.gov/pub/iono_daily/rapid/jplg{doy}0.{yy}i.gz"
NOAA_IONEX_URL = "https://ftp.aiub.unibe.ch/CODE/{year}/CODG{doy}0.{yy}I.gz"

# Cache the last fetched TEC map in memory
_tec_cache = {"data": None, "fetched_at": None, "vtec": None}


def _get_doy(dt: datetime) -> tuple[str, str]:
    """Get day-of-year and 2-digit year strings for IONEX filename."""
    doy = str(dt.timetuple().tm_yday).zfill(3)
    yy = str(dt.year)[2:]
    return doy, yy


def _parse_ionex_vtec(content: str, lat: float, lon: float) -> Optional[float]:
    """
    Parse IONEX file and extract vertical TEC at given lat/lon.
    Returns VTEC in TECU or None if parsing fails.
    IONEX format: TEC maps at specific epochs throughout the day.
    """
    try:
        lines = content.splitlines()
        in_map = False
        tec_values = []
        lat_start = lon_start = lat_step = lon_step = None
        epoch_maps = []
        current_map = []

        for line in lines:
            if "START OF TEC MAP" in line:
                in_map = True
                current_map = []
                continue
            if "END OF TEC MAP" in line:
                in_map = False
                if current_map:
                    epoch_maps.append(current_map[:])
                    current_map = []
                continue
            if "LAT/LON1/LON2/DLON/H" in line:
                parts = line.split()
                lat_val = float(parts[0])
                lon1 = float(parts[1])
                lon2 = float(parts[2])
                dlon = float(parts[3])
                current_map.append((lat_val, lon1, dlon, []))
                continue
            if in_map and current_map and line.strip() and not any(
                kw in line for kw in ["LAT/LON", "END", "START", "EPOCH"]
            ):
                try:
                    vals = [int(x) for x in line.split()]
                    current_map[-1][3].extend(vals)
                except ValueError:
                    pass

        if not epoch_maps:
            return None

        # Use the map closest to current time (middle of day as approximation)
        tec_map = epoch_maps[len(epoch_maps) // 2]

        # Find the row closest to our latitude
        best_row = min(tec_map, key=lambda r: abs(r[0] - lat))
        lat_val, lon1, dlon, tec_row = best_row

        if not tec_row:
            return None

        # Find column closest to our longitude
        lon_idx = round((lon - lon1) / dlon)
        lon_idx = max(0, min(lon_idx, len(tec_row) - 1))

        raw_tec = tec_row[lon_idx]
        # IONEX scale factor is typically 0.1
        vtec = raw_tec * 0.1
        return vtec

    except Exception as e:
        logger.warning(f"IONEX parse error: {e}")
        return None


def fetch_tec(lat: float, lon: float) -> dict:
    """
    Fetch current ionospheric TEC for a location.
    Returns dict with vtec value and quality assessment.
    """
    global _tec_cache

    # Return cache if fresh (< 2 hours old)
    if _tec_cache["fetched_at"]:
        age = (datetime.now(timezone.utc) - _tec_cache["fetched_at"]).total_seconds()
        if age < 7200 and _tec_cache["vtec"] is not None:
            return _build_tec_result(_tec_cache["vtec"])

    # Try yesterday's rapid IONEX from JPL (today's may not be published yet)
    dt = datetime.now(timezone.utc) - timedelta(days=1)
    doy, yy = _get_doy(dt)
    url = JPL_IONEX_URL.format(doy=doy, yy=yy)

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()

        # Decompress gzip
        with gzip.open(io.BytesIO(resp.content), 'rt', encoding='latin-1') as f:
            content = f.read()

        vtec = _parse_ionex_vtec(content, lat, lon)
        if vtec is not None:
            _tec_cache = {
                "data": content,
                "fetched_at": datetime.now(timezone.utc),
                "vtec": vtec,
            }
            logger.info(f"Fetched IONEX TEC: {vtec:.1f} TECU at ({lat}, {lon})")
            return _build_tec_result(vtec)

    except Exception as e:
        logger.warning(f"IONEX fetch failed: {e}")

    # Fallback: estimate TEC from space weather Kp index
    return _estimate_tec_from_kp()


def _build_tec_result(vtec: float) -> dict:
    """Build TEC result dict with quality classification."""
    if vtec <= 5:
        condition = "LOW"
        penalty = 0.0
    elif vtec <= 15:
        condition = "MODERATE"
        penalty = 3.0
    elif vtec <= 30:
        condition = "HIGH"
        penalty = 7.0
    else:
        condition = "VERY_HIGH"
        penalty = 12.0

    return {
        "vtec_tecu": round(vtec, 1),
        "condition": condition,
        "score_penalty": penalty,
        "source": "IONEX",
        "note": f"Ionospheric TEC {vtec:.1f} TECU — {condition.lower()} scintillation risk",
    }


def _estimate_tec_from_kp() -> dict:
    """Fallback: estimate TEC from Kp index when IONEX unavailable."""
    try:
        from space_weather import get_kp_index
        kp_data = get_kp_index()
        kp = kp_data.get("kp", 2.0)
        # Rough empirical mapping: Kp -> TECU
        estimated_vtec = 5.0 + (kp * 2.5)
    except Exception:
        estimated_vtec = 10.0

    result = _build_tec_result(estimated_vtec)
    result["source"] = "estimated_from_kp"
    result["note"] = f"Estimated TEC {estimated_vtec:.1f} TECU (IONEX unavailable)"
    return result
