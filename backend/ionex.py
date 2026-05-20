"""
OrbitGuard Ionospheric TEC Module v2
Uses NOAA SWPC real-time ionospheric data — same source as Kp/F10.7.
No gzip, no auth, no NASA Earthdata account needed.
Falls back to Kp-based estimation if NOAA TEC is unavailable.
"""

import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# NOAA SWPC real-time ionospheric TEC product
NOAA_TEC_URL = "https://services.swpc.noaa.gov/json/ionospheric_tec.json"
NOAA_ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"

_tec_cache = {"vtec": None, "fetched_at": None}


def fetch_noaa_tec(lat: float, lon: float) -> dict:
    """
    Fetch real-time TEC from NOAA SWPC ionospheric product.
    Returns dict with vtec, condition, penalty, source.
    """
    global _tec_cache

    # Use cache if fresh (< 30 min)
    if _tec_cache["fetched_at"]:
        age = (datetime.now(timezone.utc) - _tec_cache["fetched_at"]).total_seconds()
        if age < 1800 and _tec_cache["vtec"] is not None:
            return _build_tec_result(_tec_cache["vtec"], "NOAA_SWPC")

    try:
        resp = requests.get(NOAA_TEC_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        # NOAA TEC product returns global map data
        # Extract the most recent global mean TEC value
        if isinstance(data, list) and len(data) > 0:
            # Find entry closest to our lat/lon if available
            # Otherwise use the most recent global value
            latest = data[-1] if data else None
            if latest:
                # Try to get VTEC value from various field names
                vtec = (
                    latest.get("vtec") or
                    latest.get("tec") or
                    latest.get("value") or
                    latest.get("global_mean_tec")
                )
                if vtec is not None:
                    vtec = float(vtec)
                    _tec_cache = {"vtec": vtec, "fetched_at": datetime.now(timezone.utc)}
                    return _build_tec_result(vtec, "NOAA_SWPC")

    except Exception as e:
        logger.warning(f"NOAA TEC fetch failed: {e}")

    # Fallback: estimate from Kp + solar flux
    return _estimate_from_space_weather()


def _estimate_from_space_weather() -> dict:
    """Estimate TEC from Kp index when direct TEC unavailable."""
    try:
        from space_weather import get_kp_index, get_solar_flux
        kp_data = get_kp_index()
        flux_data = get_solar_flux()
        kp = kp_data.get("kp", 2.0)
        f107 = flux_data.get("f107", 150.0)
        # Empirical formula: TEC increases with solar flux and Kp
        base_tec = 5.0 + (f107 - 70.0) * 0.08
        storm_add = max(0, (kp - 3.0) * 3.0)
        estimated = round(max(2.0, base_tec + storm_add), 1)
        result = _build_tec_result(estimated, "estimated_from_kp_f107")
        result["note"] = f"Estimated TEC {estimated} TECU from Kp={kp:.1f}, F10.7={f107:.0f}"
        return result
    except Exception:
        return _build_tec_result(10.0, "default_fallback")


def _build_tec_result(vtec: float, source: str) -> dict:
    """Build standardised TEC result with condition and score penalty."""
    if vtec <= 5:
        condition, penalty = "LOW", 0.0
    elif vtec <= 15:
        condition, penalty = "MODERATE", 3.0
    elif vtec <= 30:
        condition, penalty = "HIGH", 7.0
    else:
        condition, penalty = "VERY_HIGH", 12.0

    is_real = source == "NOAA_SWPC"
    note = (
        f"TEC {vtec:.1f} TECU — {condition.lower()} ionospheric scintillation risk"
        if is_real else
        f"Estimated TEC {vtec:.1f} TECU (live data temporarily unavailable)"
    )

    return {
        "vtec_tecu": round(vtec, 1),
        "condition": condition,
        "score_penalty": penalty,
        "source": source,
        "is_real_data": is_real,
        "note": note,
    }


def fetch_tec(lat: float, lon: float) -> dict:
    """Public interface — fetch TEC for a location."""
    return fetch_noaa_tec(lat, lon)
