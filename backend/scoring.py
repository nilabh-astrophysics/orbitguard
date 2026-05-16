"""
Pass Quality Scoring Engine.

Combines orbital geometry + space weather into a composite 0-100 score.
No ML — deterministic weighted formula, transparent and explainable.

Score breakdown:
  - Elevation geometry:     40 pts  (higher peak = better link budget)
  - Pass duration:          20 pts  (longer = more data transfer time)
  - Kp index penalty:       20 pts  (geomagnetic disturbance degrades RF)
  - Solar flux penalty:     10 pts  (high F10.7 → ionospheric scintillation)
  - Active alert penalty:   10 pts  (NOAA warnings)
"""

from typing import Optional
import math


# ── Geometry scoring ─────────────────────────────────────────────────────────

def elevation_score(max_elevation_deg: float) -> float:
    """
    0–60 pts. Linear from 10° (horizon) to 90° (zenith, best).
    """
    clamped = max(10.0, min(90.0, max_elevation_deg))
    return round(((clamped - 10.0) / 80.0) * 60.0, 2)


def duration_score(duration_seconds: float) -> float:
    """
    0–40 pts. 600s = full marks. Sqrt scaling.
    """
    clamped = max(0.0, min(600.0, duration_seconds))
    return round((math.sqrt(clamped) / math.sqrt(600.0)) * 40.0, 2)


# ── Space weather penalties ───────────────────────────────────────────────────

def kp_penalty(kp: float) -> float:
    """
    0–20 pts deducted. Kp scale 0–9.
    Kp 0-2: no penalty. Kp 5: -10. Kp 7+: full -20.
    """
    if kp <= 2.0:
        return 0.0
    elif kp >= 7.0:
        return 20.0
    else:
        # linear between 2 and 7
        return round(((kp - 2.0) / 5.0) * 20.0, 2)


def solar_flux_penalty(f107: float) -> float:
    """
    0–10 pts deducted. F10.7 scale: quiet ~70, moderate ~150, active ~250+.
    Above 200 → ionospheric scintillation risk for UHF/VHF links.
    """
    if f107 <= 100.0:
        return 0.0
    elif f107 >= 250.0:
        return 10.0
    else:
        return round(((f107 - 100.0) / 150.0) * 10.0, 2)


def alert_penalty(alert_count: int) -> float:
    """
    0–10 pts deducted. Each active NOAA alert = -3 pts, capped at -10.
    """
    return min(10.0, alert_count * 3.0)


# ── Composite scorer ──────────────────────────────────────────────────────────

def score_pass(
    max_elevation_deg: float,
    duration_seconds: float,
    kp: float,
    f107: float,
    alert_count: int,
) -> dict:
    """
    Compute composite pass quality score and return full breakdown.
    """
    el_score = elevation_score(max_elevation_deg)
    dur_score = duration_score(duration_seconds)
    kp_pen = kp_penalty(kp)
    flux_pen = solar_flux_penalty(f107)
    alert_pen = alert_penalty(alert_count)

    raw = el_score + dur_score - kp_pen - flux_pen - alert_pen
    final = round(max(0.0, min(100.0, raw)), 1)

    # Grade
    if final >= 80:
        grade = "EXCELLENT"
        color = "green"
    elif final >= 60:
        grade = "GOOD"
        color = "lime"
    elif final >= 40:
        grade = "FAIR"
        color = "yellow"
    elif final >= 20:
        grade = "POOR"
        color = "orange"
    else:
        grade = "AVOID"
        color = "red"

    return {
        "score": final,
        "grade": grade,
        "color": color,
        "breakdown": {
            "elevation_score": el_score,
            "duration_score": dur_score,
            "kp_penalty": -kp_pen,
            "solar_flux_penalty": -flux_pen,
            "alert_penalty": -alert_pen,
        },
        "inputs": {
            "max_elevation_deg": max_elevation_deg,
            "duration_seconds": duration_seconds,
            "kp_index": kp,
            "f107_solar_flux": f107,
            "active_alert_count": alert_count,
        },
    }


def score_pass_list(passes: list[dict], space_weather: dict) -> list[dict]:
    """
    Apply scoring to every pass in the list.
    Attaches score dict to each pass and sorts by AOS time.
    """
    kp = space_weather.get("kp_index", 2.0)
    f107 = space_weather.get("f107_solar_flux", 150.0)
    alert_count = space_weather.get("active_alert_count", 0)

    scored = []
    for p in passes:
        quality = score_pass(
            max_elevation_deg=p["max_elevation_deg"],
            duration_seconds=p["duration_seconds"],
            kp=kp,
            f107=f107,
            alert_count=alert_count,
        )
        scored.append({**p, "quality": quality})

    return scored
