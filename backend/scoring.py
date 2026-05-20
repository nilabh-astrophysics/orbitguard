"""
OrbitGuard Pass Quality Scoring Engine v3
Recalibrated weights — fixes over-penalization from alerts.

Score breakdown (max 100):
  Elevation geometry:       0–60 pts  (10°→0, 90°→60)
  Pass duration:            0–40 pts  (0s→0, 600s→40, sqrt scale)
  Kp index penalty:         0–20 pts  (Kp≤2: 0, Kp≥7: 20)
  Solar flux penalty:       0–10 pts  (F10.7≤100: 0, ≥250: 10)
  Active alert penalty:     0–5 pts   (1pt per alert, cap 5)
  Ionospheric TEC penalty:  0–8 pts   (LOW: 0, MODERATE: 3, HIGH: 6, VERY_HIGH: 8)
"""

import math


def elevation_score(max_elevation_deg: float) -> float:
    clamped = max(10.0, min(90.0, max_elevation_deg))
    return round(((clamped - 10.0) / 80.0) * 60.0, 2)


def duration_score(duration_seconds: float) -> float:
    clamped = max(0.0, min(600.0, duration_seconds))
    return round((math.sqrt(clamped) / math.sqrt(600.0)) * 40.0, 2)


def kp_penalty(kp: float) -> float:
    if kp <= 2.0:
        return 0.0
    elif kp >= 7.0:
        return 20.0
    return round(((kp - 2.0) / 5.0) * 20.0, 2)


def solar_flux_penalty(f107: float) -> float:
    if f107 <= 100.0:
        return 0.0
    elif f107 >= 250.0:
        return 10.0
    return round(((f107 - 100.0) / 150.0) * 10.0, 2)


def alert_penalty(alert_count: int) -> float:
    """
    Fixed: -1 pt per alert, cap at -5.
    Previous version (-3 per alert, cap -10) was too aggressive —
    5 NOAA alerts (common during active periods) were wiping 15 pts.
    NOAA alerts are informational; Kp already captures the physical effect.
    """
    return min(5.0, float(alert_count) * 1.0)


def tec_penalty(tec_score_penalty: float) -> float:
    """Ionospheric TEC penalty, capped at 8 pts."""
    return min(8.0, max(0.0, tec_score_penalty))


def score_pass(
    max_elevation_deg: float,
    duration_seconds: float,
    kp: float,
    f107: float,
    alert_count: int,
    tec_penalty_pts: float = 0.0,
) -> dict:
    el_score = elevation_score(max_elevation_deg)
    dur_score = duration_score(duration_seconds)
    kp_pen = kp_penalty(kp)
    flux_pen = solar_flux_penalty(f107)
    alert_pen = alert_penalty(alert_count)
    ionex_pen = tec_penalty(tec_penalty_pts)

    raw = el_score + dur_score - kp_pen - flux_pen - alert_pen - ionex_pen
    final = round(max(0.0, min(100.0, raw)), 1)

    if final >= 80:
        grade, color = "EXCELLENT", "green"
    elif final >= 60:
        grade, color = "GOOD", "lime"
    elif final >= 40:
        grade, color = "FAIR", "yellow"
    elif final >= 20:
        grade, color = "POOR", "orange"
    else:
        grade, color = "AVOID", "red"

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
            "ionospheric_penalty": -ionex_pen,
        },
        "inputs": {
            "max_elevation_deg": max_elevation_deg,
            "duration_seconds": duration_seconds,
            "kp_index": kp,
            "f107_solar_flux": f107,
            "active_alert_count": alert_count,
            "tec_penalty_pts": tec_penalty_pts,
        },
    }


def score_pass_list(passes: list, space_weather: dict, tec_data: dict = None) -> list:
    kp = space_weather.get("kp_index", 2.0)
    f107 = space_weather.get("f107_solar_flux", 150.0)
    alert_count = space_weather.get("active_alert_count", 0)
    tec_pen = tec_data.get("score_penalty", 0.0) if tec_data else 0.0

    return [
        {**p, "quality": score_pass(
            max_elevation_deg=p["max_elevation_deg"],
            duration_seconds=p["duration_seconds"],
            kp=kp, f107=f107,
            alert_count=alert_count,
            tec_penalty_pts=tec_pen,
        )}
        for p in passes
    ]
