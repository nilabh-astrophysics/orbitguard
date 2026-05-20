"""
OrbitGuard Space Weather Module v2
Fixed Kp severity thresholds:
  Kp 0-3 = QUIET
  Kp 4-5 = MINOR
  Kp 6   = MODERATE
  Kp 7+  = SEVERE
"""

import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

NOAA_KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
NOAA_SOLAR_FLUX_URL = "https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json"
NOAA_ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"


def get_kp_index() -> dict:
    try:
        resp = requests.get(NOAA_KP_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return {"kp": 2.0, "source": "default"}
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
        }
    except Exception as e:
        logger.warning(f"Solar flux fetch failed: {e}")
        return {"f107": 150.0, "source": "default_fallback"}


def get_active_alerts() -> list:
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
        return active[:5]
    except Exception as e:
        logger.warning(f"Alerts fetch failed: {e}")
        return []


def classify_severity(kp: float, alert_count: int) -> dict:
    """
    Correct Kp-based severity classification for satellite operations.
    Based on NOAA geomagnetic storm scale (G-scale):
      G0 (Kp 0-3): Quiet     — nominal operations
      G1 (Kp 4-5): Minor     — minor impact on HF radio, aurora at high latitudes
      G2 (Kp 6):   Moderate  — HF degradation, increased drag on LEO sats
      G3+ (Kp 7+): Severe    — widespread HF blackout, satellite orientation issues
    """
    if kp >= 7.0:
        return {
            "severity": "SEVERE",
            "g_scale": "G3+",
            "ops_impact": "Widespread HF blackout. Satellite orientation issues possible. Avoid critical uplink passes.",
            "color": "red",
        }
    elif kp >= 6.0:
        return {
            "severity": "MODERATE",
            "g_scale": "G2",
            "ops_impact": "HF radio degradation at mid-latitudes. Increased atmospheric drag on LEO. Monitor passes carefully.",
            "color": "orange",
        }
    elif kp >= 4.0:
        return {
            "severity": "MINOR",
            "g_scale": "G1",
            "ops_impact": "Minor HF radio fluctuations. Low-latitude aurora possible. Most operations nominal.",
            "color": "yellow",
        }
    else:
        return {
            "severity": "QUIET",
            "g_scale": "G0",
            "ops_impact": "Nominal space weather. No significant impact on satellite operations expected.",
            "color": "green",
        }


def get_space_weather_snapshot() -> dict:
    kp_data = get_kp_index()
    flux_data = get_solar_flux()
    alerts = get_active_alerts()

    kp = kp_data["kp"]
    f107 = flux_data["f107"]
    alert_count = len(alerts)

    severity_info = classify_severity(kp, alert_count)

    return {
        "kp_index": kp,
        "f107_solar_flux": f107,
        "active_alert_count": alert_count,
        "active_alerts": alerts,
        "severity": severity_info["severity"],
        "g_scale": severity_info["g_scale"],
        "ops_impact": severity_info["ops_impact"],
        "severity_color": severity_info["color"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "kp": kp_data["source"],
            "f107": flux_data["source"],
        },
    }
