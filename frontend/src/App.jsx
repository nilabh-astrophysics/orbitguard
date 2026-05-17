import { useState, useEffect, useCallback } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

// Replace this with your actual demo key from /keys/register
const DEMO_API_KEY = process.env.REACT_APP_DEMO_API_KEY || "";

const HEADERS = {
  "Content-Type": "application/json",
  ...(DEMO_API_KEY ? { "X-Api-Key": DEMO_API_KEY } : {}),
};

const POPULAR_SATS = [
  { name: "ISS", norad_id: 25544 },
  { name: "LANDSAT 9", norad_id: 49260 },
  { name: "SENTINEL-2A", norad_id: 40697 },
  { name: "AQUA", norad_id: 27424 },
  { name: "NOAA 18", norad_id: 28654 },
];

function scoreColor(score) {
  if (score >= 80) return "#1D9E75";
  if (score >= 60) return "#639922";
  if (score >= 40) return "#BA7517";
  if (score >= 20) return "#D85A30";
  return "#E24B4A";
}

function gradeStyle(grade) {
  const map = {
    EXCELLENT: { bg: "#E1F5EE", color: "#085041" },
    GOOD:      { bg: "#EAF3DE", color: "#27500A" },
    FAIR:      { bg: "#FAEEDA", color: "#633806" },
    POOR:      { bg: "#FAECE7", color: "#4A1B0C" },
    AVOID:     { bg: "#FCEBEB", color: "#501313" },
  };
  return map[grade] || map.AVOID;
}

function ScoreRing({ score }) {
  const r = 20, circ = 2 * Math.PI * r;
  const offset = circ * (1 - score / 100);
  const col = scoreColor(score);
  return (
    <div style={{ width: 48, height: 48, position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <svg width="48" height="48" style={{ position: "absolute", top: 0, left: 0, transform: "rotate(-90deg)" }}>
        <circle cx="24" cy="24" r={r} fill="none" stroke="rgba(128,128,128,0.15)" strokeWidth="4" />
        <circle cx="24" cy="24" r={r} fill="none" stroke={col} strokeWidth="4"
          strokeDasharray={circ.toFixed(1)} strokeDashoffset={offset.toFixed(1)} strokeLinecap="round" />
      </svg>
      <span style={{ fontSize: 12, fontWeight: 500, color: col, position: "relative", zIndex: 1 }}>
        {score.toFixed(0)}
      </span>
    </div>
  );
}

function PassCard({ pass }) {
  const aos = new Date(pass.aos);
  const timeStr = aos.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  const dateStr = aos.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const mins = Math.floor(pass.duration_seconds / 60);
  const secs = pass.duration_seconds % 60;
  const durStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  const { score, grade } = pass.quality;
  const gs = gradeStyle(grade);
  return (
    <div style={{
      background: "var(--color-background-primary, #fff)",
      border: "0.5px solid #e0e0e0",
      borderRadius: 12, padding: "0.9rem 1.1rem",
      display: "grid", gridTemplateColumns: "52px 1fr 1fr 1fr 90px",
      gap: 12, alignItems: "center",
    }}>
      <ScoreRing score={score} />
      <div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>{timeStr}</div>
        <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>{dateStr}</div>
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>{pass.max_elevation_deg.toFixed(1)}°</div>
        <div style={{ fontSize: 11, color: "#888", marginTop: 1 }}>max elevation</div>
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>{durStr}</div>
        <div style={{ fontSize: 11, color: "#888", marginTop: 1 }}>duration</div>
      </div>
      <span style={{ fontSize: 11, fontWeight: 500, padding: "4px 10px", borderRadius: 999,
        background: gs.bg, color: gs.color, textAlign: "center" }}>
        {grade}
      </span>
    </div>
  );
}

function MetricCard({ label, value, sub }) {
  return (
    <div style={{ background: "#f5f5f5", borderRadius: 8, padding: "0.85rem 1rem" }}>
      <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 500 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function App() {
  const [noradId, setNoradId] = useState(25544);
  const [lat, setLat] = useState(19.07);
  const [lon, setLon] = useState(72.87);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchForecast = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/passes/norad/${noradId}?lat=${lat}&lon=${lon}&hours_ahead=48&include_ionex=true`,
        { headers: HEADERS }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `API error ${res.status}`);
      }
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, [noradId, lat, lon]);

  useEffect(() => { fetchForecast(); }, []);

  const wx = data?.space_weather;
  const ionex = data?.ionospheric;
  const passes = data?.passes || [];
  const scores = passes.map(p => p.quality.score);
  const bestScore = scores.length ? Math.max(...scores) : null;
  const avoidCount = scores.filter(s => s < 20).length;

  const chartData = passes.map(p => ({
    time: new Date(p.aos).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }),
    score: parseFloat(p.quality.score.toFixed(1)),
  }));

  const wxBadgeStyle = {
    fontSize: 11, padding: "3px 8px", borderRadius: 6, fontWeight: 500,
    background: wx?.severity === "SEVERE" ? "#FCEBEB" : wx?.severity === "MODERATE" ? "#FAEEDA" : "#E1F5EE",
    color: wx?.severity === "SEVERE" ? "#501313" : wx?.severity === "MODERATE" ? "#633806" : "#085041",
  };

  return (
    <div style={{ padding: "1.25rem", fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif", maxWidth: 900, margin: "0 auto", color: "#111" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
        borderBottom: "0.5px solid #e0e0e0", paddingBottom: "0.75rem", marginBottom: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 18, fontWeight: 500 }}>
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#1D9E75" }} />
          OrbitGuard
          <span style={{ fontSize: 12, color: "#888", fontWeight: 400 }}>pass quality forecaster v2</span>
        </div>
        {wx && <span style={wxBadgeStyle}>{wx.severity}</span>}
      </div>

      {/* Space weather bar */}
      {wx && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "0.75rem 1rem",
          background: "#f5f5f5", borderRadius: 8, marginBottom: "1rem" }}>
          {[["Kp index", wx.kp_index?.toFixed(1)],
            ["F10.7 flux", wx.f107_solar_flux?.toFixed(0)],
            ["Active alerts", wx.active_alert_count],
            ["Condition", wx.severity],
            ...(ionex ? [["TEC", `${ionex.vtec_tecu} TECU`], ["Ionosphere", ionex.condition]] : [])
          ].map(([lbl, val], i) => (
            <div key={lbl} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1 }}>
              <span style={{ fontSize: 15, fontWeight: 500 }}>{val}</span>
              <span style={{ fontSize: 11, color: "#888", marginTop: 2 }}>{lbl}</span>
            </div>
          ))}
        </div>
      )}

      {/* Metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: "1rem" }}>
        <MetricCard label="Satellite" value={data?.satellite_name?.split(" ")[0] || "—"} sub={`NORAD ${noradId}`} />
        <MetricCard label="Passes (48h)" value={data?.pass_count ?? "—"} sub="forecast horizon" />
        <MetricCard label="Best score" value={bestScore !== null ? bestScore.toFixed(0) : "—"} sub="highest quality" />
        <MetricCard label="Avoid" value={avoidCount} sub="score < 20" />
      </div>

      {/* Controls */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 10, marginBottom: "1rem", alignItems: "end" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12, color: "#888" }}>Satellite</label>
          <select value={noradId} onChange={e => setNoradId(Number(e.target.value))}
            style={{ fontSize: 14, padding: "6px 8px", borderRadius: 6, border: "1px solid #ddd" }}>
            {POPULAR_SATS.map(s => <option key={s.norad_id} value={s.norad_id}>{s.name} ({s.norad_id})</option>)}
          </select>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12, color: "#888" }}>Latitude</label>
          <input type="number" step="0.01" value={lat} onChange={e => setLat(Number(e.target.value))}
            style={{ fontSize: 14, padding: "6px 8px", borderRadius: 6, border: "1px solid #ddd" }} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 12, color: "#888" }}>Longitude</label>
          <input type="number" step="0.01" value={lon} onChange={e => setLon(Number(e.target.value))}
            style={{ fontSize: 14, padding: "6px 8px", borderRadius: 6, border: "1px solid #ddd" }} />
        </div>
        <button onClick={fetchForecast} disabled={loading}
          style={{ background: "#1D9E75", color: "#fff", border: "none", borderRadius: 8,
            padding: "0 18px", height: 36, fontSize: 14, fontWeight: 500, cursor: "pointer" }}>
          {loading ? "Loading..." : "Forecast ↗"}
        </button>
      </div>

      {error && (
        <div style={{ background: "#FCEBEB", color: "#501313", borderRadius: 8,
          padding: "0.75rem 1rem", fontSize: 13, marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      {/* Ionosphere note */}
      {ionex && (
        <div style={{ fontSize: 12, color: "#888", marginBottom: "0.75rem", padding: "6px 10px",
          background: "#f9f9f9", borderRadius: 6 }}>
          🌐 {ionex.note} — penalty applied to all scores
        </div>
      )}

      {/* Chart */}
      {chartData.length > 0 && (
        <div style={{ marginBottom: "1rem" }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "#888", textTransform: "uppercase",
            letterSpacing: "0.06em", marginBottom: "0.6rem" }}>Pass quality timeline</div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: -20 }}>
              <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#888" }} axisLine={false} tickLine={false} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#888" }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(v) => [v.toFixed(1), "Score"]} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                {chartData.map((entry, i) => <Cell key={i} fill={scoreColor(entry.score)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Pass list */}
      <div style={{ fontSize: 13, fontWeight: 500, color: "#888", textTransform: "uppercase",
        letterSpacing: "0.06em", marginBottom: "0.6rem" }}>Upcoming pass windows</div>
      {loading ? (
        <div style={{ textAlign: "center", padding: "2rem", color: "#888", fontSize: 14 }}>
          Computing pass windows...
        </div>
      ) : passes.length === 0 ? (
        <div style={{ textAlign: "center", padding: "2.5rem", color: "#888", fontSize: 14 }}>
          No passes found. Try adjusting coordinates or satellite.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {passes.map((p, i) => <PassCard key={i} pass={p} />)}
        </div>
      )}
    </div>
  );
}
