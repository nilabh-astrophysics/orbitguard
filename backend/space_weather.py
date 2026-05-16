"""
Space weather ingestion from NOAA SWPC and NASA DONKI APIs.
Returns Kp index, solar flux F10.7, and active event flags.
"""

import requests
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

NOAA_KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
NOAA_SOLAR_FLUX_URL = "https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json"
NOAA_ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"
NASA_DONKI_BASE = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get"


def get_kp_index() -> dict:
    """Fetch latest planetary Kp index from NOAA SWPC."""
    try:
        resp = requests.get(NOAA_KP_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return {"kp": 2.0, "source": "default", "timestamp": None}
        latest = data[-1]
        return {
            "kp": float(latest.get("kp_index", 2.0)),
            "source": "NOAA_SWPC",
            "timestamp": latest.get("time_tag"),
        }
    except Exception as e:
        logger.warning(f"Kp fetch failed: {e}")
        return {"kp": 2.0, "source": "default_fallback", "timestamp": None}


def get_solar_flux() -> dict:
    """Fetch latest F10.7 solar flux index from NOAA."""
    try:
        resp = requests.get(NOAA_SOLAR_FLUX_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return {"f107": 150.0, "source": "default"}
        latest = data[-1]
        return {
            "f107": float(latest.get("f10.7", 150.0)),
            "source": "NOAA_SWPC",
            "year_month": latest.get("time-tag"),
        }
    except Exception as e:
        logger.warning(f"Solar flux fetch failed: {e}")
        return {"f107": 150.0, "source": "default_fallback"}


def get_active_alerts() -> list[dict]:
    """Fetch current NOAA space weather alerts/warnings."""
    try:
        resp = requests.get(NOAA_ALERTS_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        active = []
        for alert in data:
            msg = alert.get("message", "")
            if any(kw in msg.upper() for kw in ["WARNING", "WATCH", "ALERT", "STORM"]):
                active.append({
                    "type": alert.get("product_id", "UNKNOWN"),
                    "issued": alert.get("issue_datetime"),
                    "message_snippet": msg[:120].strip(),
                })
        return active[:5]  # cap at 5
    except Exception as e:
        logger.warning(f"Alerts fetch failed: {e}")
        return []


def get_space_weather_snapshot() -> dict:
    """Aggregate all space weather signals into a single snapshot."""
    kp_data = get_kp_index()
    flux_data = get_solar_flux()
    alerts = get_active_alerts()

    kp = kp_data["kp"]
    f107 = flux_data["f107"]
    alert_count = len(alerts)

    # Severity classification
    if kp >= 7 or alert_count >= 3:
        severity = "SEVERE"
    elif kp >= 5 or alert_count >= 1:
        severity = "MODERATE"
    elif kp >= 3:
        severity = "MINOR"
    else:
        severity = "QUIET"

    return {
        "kp_index": kp,
        "f107_solar_flux": f107,
        "active_alert_count": alert_count,
        "active_alerts": alerts,
        "severity": severity,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "kp": kp_data["source"],
            "f107": flux_data["source"],
        },
    }
