# OrbitGuard

**Satellite pass quality forecasting for ground station operators.**

Combines orbital geometry (TLE → pass windows via Skyfield) with real-time space weather (NOAA SWPC, NASA DONKI) into a composite 0–100 pass quality score.

---

## Project structure

```
orbitguard/
├── backend/          FastAPI API server
│   ├── main.py       API routes
│   ├── orbital.py    TLE fetch + pass computation (Skyfield)
│   ├── space_weather.py  NOAA/NASA data ingestion
│   ├── scoring.py    Composite quality scoring engine
│   ├── requirements.txt
│   └── railway.toml
└── frontend/         React dashboard
    ├── src/App.jsx   Main dashboard component
    ├── public/
    ├── package.json
    └── railway.toml
```

---

## Local development

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API docs at: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
REACT_APP_API_URL=http://localhost:8000 npm start
```

Dashboard at: http://localhost:3000

---

## Key API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/passes/norad/{norad_id}` | Compute scored passes by NORAD ID |
| POST | `/passes/tle` | Compute scored passes from raw TLE |
| GET | `/space-weather` | Current Kp, F10.7, NOAA alerts |
| GET | `/satellites/popular` | Quick reference NORAD IDs |

### Example

```bash
# ISS passes over Mumbai (lat=19.07, lon=72.87)
curl "http://localhost:8000/passes/norad/25544?lat=19.07&lon=72.87"
```

Response:
```json
{
  "satellite_name": "ISS (ZARYA)",
  "norad_id": 25544,
  "pass_count": 7,
  "space_weather": { "kp_index": 3.2, "severity": "MINOR", ... },
  "passes": [
    {
      "aos": "2025-09-01T04:22:00+00:00",
      "los": "2025-09-01T04:29:00+00:00",
      "max_elevation_deg": 67.4,
      "duration_seconds": 420,
      "quality": {
        "score": 74.1,
        "grade": "GOOD",
        "breakdown": {
          "elevation_score": 42.75,
          "duration_score": 33.47,
          "kp_penalty": -4.0,
          "solar_flux_penalty": 0,
          "alert_penalty": 0
        }
      }
    }
  ]
}
```

---

## Scoring formula

| Component | Weight | Logic |
|-----------|--------|-------|
| Max elevation | 0–60 pts | Linear: 10°→0, 90°→60 |
| Pass duration | 0–40 pts | sqrt scale: 0s→0, 600s→40 |
| Kp penalty | −0 to −20 | Kp≤2: no penalty; Kp≥7: −20 |
| Solar flux penalty | −0 to −10 | F10.7≤100: none; ≥250: −10 |
| Alert penalty | −0 to −10 | −3 per active NOAA alert, capped |

**Score → Grade**: 80–100 EXCELLENT · 60–79 GOOD · 40–59 FAIR · 20–39 POOR · 0–19 AVOID

---

## Deploy to Railway

### Backend service
1. Create new Railway project → "Deploy from GitHub"
2. Point to `backend/` directory
3. Railway auto-detects `railway.toml` and `requirements.txt`
4. No environment variables required (all data is from public APIs)

### Frontend service
1. Add a second service in same Railway project
2. Point to `frontend/` directory
3. Set environment variable: `REACT_APP_API_URL=https://your-backend.railway.app`
4. Railway builds with `npm run build`

### CORS
Backend allows all origins by default. Before launch, update `main.py`:
```python
allow_origins=["https://your-frontend.railway.app"]
```

---

## Data sources

| Source | Data | URL |
|--------|------|-----|
| CelesTrak | TLE files | celestrak.org |
| NOAA SWPC | Kp index, solar flux, alerts | services.swpc.noaa.gov |
| NASA DONKI | Solar flares, CMEs, geomagnetic storms | kauai.ccmc.gsfc.nasa.gov/DONKI |

All sources are free and require no API keys.

---

## Roadmap (weeks 2–4)

- [ ] NASA CDDIS IONEX integration (ionospheric TEC maps)
- [ ] Email alert when high-quality pass is <2h away
- [ ] Multi-satellite dashboard (track 5 sats simultaneously)
- [ ] Historical pass quality analytics
- [ ] REST API key system + usage tracking (prep for monetization)
- [ ] Webhook support for integration with ground station schedulers

---

## Revenue model

| Tier | Price | Limits |
|------|-------|--------|
| Free | $0 | 1 satellite, 7-day forecast, API key required |
| Hobbyist | $49/mo | 5 satellites, 30-day forecast, email alerts |
| Commercial | $299/mo | Unlimited satellites, priority alerts, analytics |
| Enterprise API | $999/mo | White-label, SLA, custom integrations |

## Target customers

- University CubeSat teams (200+ active globally)
- Small commercial satellite operators
- Amateur radio operators (AMSAT community)
- Ground station network providers (AWS Ground Station, Leaf Space)
