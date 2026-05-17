"""
OrbitGuard Alert System
Sends email alerts via Resend when a high-quality pass is approaching.
Runs as a background scheduler inside FastAPI.
"""

import os
import logging
import asyncio
import httpx
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "alerts@orbitguard.app")
RESEND_URL = "https://api.resend.com/emails"


async def send_alert_email(
    to_email: str,
    satellite_name: str,
    norad_id: int,
    aos: str,
    score: float,
    grade: str,
    max_elevation: float,
    duration_seconds: int,
    kp_index: float,
    severity: str,
) -> bool:
    """Send a pass alert email via Resend. Returns True on success."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email")
        return False

    aos_dt = datetime.fromisoformat(aos.replace("Z", "+00:00"))
    aos_str = aos_dt.strftime("%B %d at %H:%M UTC")
    mins = duration_seconds // 60
    secs = duration_seconds % 60
    dur_str = f"{mins}m {secs}s"

    grade_color = {
        "EXCELLENT": "#1D9E75",
        "GOOD": "#639922",
        "FAIR": "#BA7517",
        "POOR": "#D85A30",
        "AVOID": "#E24B4A",
    }.get(grade, "#888888")

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px;">
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:24px;">
        <div style="width:10px;height:10px;border-radius:50%;background:#1D9E75;"></div>
        <span style="font-size:18px;font-weight:500;">OrbitGuard</span>
      </div>

      <h2 style="font-size:22px;font-weight:500;margin:0 0 8px;">
        Upcoming pass alert — {satellite_name}
      </h2>
      <p style="color:#666;margin:0 0 24px;">A high-quality pass window is approaching.</p>

      <div style="background:#f9f9f9;border-radius:12px;padding:20px 24px;margin-bottom:24px;">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;">Pass time</div>
            <div style="font-size:18px;font-weight:500;margin-top:4px;">{aos_str}</div>
          </div>
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;">Quality score</div>
            <div style="font-size:18px;font-weight:500;color:{grade_color};margin-top:4px;">{score:.0f} — {grade}</div>
          </div>
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;">Max elevation</div>
            <div style="font-size:16px;font-weight:500;margin-top:4px;">{max_elevation:.1f}°</div>
          </div>
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;">Duration</div>
            <div style="font-size:16px;font-weight:500;margin-top:4px;">{dur_str}</div>
          </div>
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;">Space weather</div>
            <div style="font-size:16px;font-weight:500;margin-top:4px;">Kp {kp_index:.1f} — {severity}</div>
          </div>
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;">NORAD ID</div>
            <div style="font-size:16px;font-weight:500;margin-top:4px;">{norad_id}</div>
          </div>
        </div>
      </div>

      <a href="https://orbitguard-1.onrender.com" 
         style="display:inline-block;background:#1D9E75;color:#fff;text-decoration:none;
                padding:10px 20px;border-radius:8px;font-size:14px;font-weight:500;">
        View full forecast →
      </a>

      <p style="color:#aaa;font-size:12px;margin-top:32px;">
        You're receiving this because you subscribed to pass alerts on OrbitGuard.<br>
        To unsubscribe, delete this subscription via the API.
      </p>
    </div>
    """

    payload = {
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"🛰 {satellite_name} pass in ~2h — score {score:.0f} ({grade})",
        "html": html,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                RESEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                timeout=10,
            )
            if resp.status_code in (200, 201):
                logger.info(f"Alert sent to {to_email} for {satellite_name} pass at {aos}")
                return True
            else:
                logger.error(f"Resend error {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


async def run_alert_check():
    """
    Check all active subscriptions and send alerts for upcoming good passes.
    Designed to run every 15 minutes as a background task.
    """
    from database import get_active_subscriptions, mark_alerted
    from orbital import passes_from_norad
    from space_weather import get_space_weather_snapshot
    from scoring import score_pass_list

    logger.info("Running alert check...")
    subscriptions = get_active_subscriptions()
    if not subscriptions:
        return

    weather = get_space_weather_snapshot()
    now = datetime.now(timezone.utc)

    for sub in subscriptions:
        try:
            orbital = passes_from_norad(
                sub["norad_id"], sub["lat"], sub["lon"],
                sub["elevation_m"], hours_ahead=6
            )
            if "error" in orbital:
                continue

            scored = score_pass_list(orbital["passes"], weather)

            for p in scored:
                score = p["quality"]["score"]
                grade = p["quality"]["grade"]
                aos_dt = datetime.fromisoformat(p["aos"].replace("Z", "+00:00"))

                # Check: pass is within alert window, score meets threshold
                hours_until = (aos_dt - now).total_seconds() / 3600
                if not (0.5 <= hours_until <= sub["alert_hours_ahead"]):
                    continue
                if score < sub["min_score"]:
                    continue

                # Check: haven't already alerted for this sub recently
                if sub["last_alerted"]:
                    last = datetime.fromisoformat(sub["last_alerted"])
                    if (now - last).total_seconds() < 3600:
                        continue

                # Send alert
                sent = await send_alert_email(
                    to_email=sub["email"],
                    satellite_name=sub["satellite_name"] or f"NORAD {sub['norad_id']}",
                    norad_id=sub["norad_id"],
                    aos=p["aos"],
                    score=score,
                    grade=grade,
                    max_elevation=p["max_elevation_deg"],
                    duration_seconds=p["duration_seconds"],
                    kp_index=weather["kp_index"],
                    severity=weather["severity"],
                )
                if sent:
                    mark_alerted(sub["id"], p["aos"], score, grade)

        except Exception as e:
            logger.error(f"Alert check failed for sub {sub['id']}: {e}")

    logger.info("Alert check complete.")


async def alert_scheduler():
    """Background task: run alert check every 15 minutes."""
    while True:
        try:
            await run_alert_check()
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        await asyncio.sleep(900)  # 15 minutes
