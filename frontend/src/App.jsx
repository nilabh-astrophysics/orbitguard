import { useState, useEffect, useCallback, useRef } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { createClient } from "@supabase/supabase-js";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";
const SUPABASE_URL = process.env.REACT_APP_SUPABASE_URL || "";
const SUPABASE_ANON = process.env.REACT_APP_SUPABASE_ANON_KEY || "";
const supabase = createClient(SUPABASE_URL, SUPABASE_ANON);

const POPULAR_SATS = [
  { name: "ISS (ZARYA)", norad_id: 25544 },
  { name: "LANDSAT 9", norad_id: 49260 },
  { name: "SENTINEL-2A", norad_id: 40697 },
  { name: "AQUA", norad_id: 27424 },
  { name: "NOAA 18", norad_id: 28654 },
  { name: "TERRA", norad_id: 25994 },
  { name: "STARLINK-1007", norad_id: 44713 },
  { name: "CARTOSAT-3", norad_id: 44857 },
  { name: "NOAA-20", norad_id: 43013 },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreColor(s) {
  if (s >= 80) return "#1D9E75";
  if (s >= 60) return "#639922";
  if (s >= 40) return "#BA7517";
  if (s >= 20) return "#D85A30";
  return "#E24B4A";
}

function gradeStyle(g) {
  const m = {
    EXCELLENT: { bg: "#E1F5EE", color: "#085041" },
    GOOD:      { bg: "#EAF3DE", color: "#27500A" },
    FAIR:      { bg: "#FAEEDA", color: "#633806" },
    POOR:      { bg: "#FAECE7", color: "#4A1B0C" },
    AVOID:     { bg: "#FCEBEB", color: "#501313" },
  };
  return m[g] || m.AVOID;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ScoreRing({ score }) {
  const r = 20, circ = 2 * Math.PI * r, offset = circ * (1 - score / 100), col = scoreColor(score);
  return (
    <div style={{ width: 48, height: 48, position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <svg width="48" height="48" style={{ position: "absolute", top: 0, left: 0, transform: "rotate(-90deg)" }}>
        <circle cx="24" cy="24" r={r} fill="none" stroke="rgba(128,128,128,0.15)" strokeWidth="4" />
        <circle cx="24" cy="24" r={r} fill="none" stroke={col} strokeWidth="4"
          strokeDasharray={circ.toFixed(1)} strokeDashoffset={offset.toFixed(1)} strokeLinecap="round" />
      </svg>
      <span style={{ fontSize: 12, fontWeight: 500, color: col, position: "relative", zIndex: 1 }}>{score.toFixed(0)}</span>
    </div>
  );
}

function PassCard({ pass }) {
  const aos = new Date(pass.aos);
  const timeStr = aos.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  const dateStr = aos.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const mins = Math.floor(pass.duration_seconds / 60), secs = pass.duration_seconds % 60;
  const { score, grade } = pass.quality;
  const gs = gradeStyle(grade);
  return (
    <div style={{ background: "#fff", border: "0.5px solid #e0e0e0", borderRadius: 12, padding: "0.9rem 1.1rem",
      display: "grid", gridTemplateColumns: "52px 1fr 1fr 1fr 90px", gap: 12, alignItems: "center" }}>
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
        <div style={{ fontSize: 14, fontWeight: 500 }}>{mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}</div>
        <div style={{ fontSize: 11, color: "#888", marginTop: 1 }}>duration</div>
      </div>
      <span style={{ fontSize: 11, fontWeight: 500, padding: "4px 10px", borderRadius: 999,
        background: gs.bg, color: gs.color, textAlign: "center" }}>{grade}</span>
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

// ── Auth Page ─────────────────────────────────────────────────────────────────

function AuthPage({ onAuth }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const handleSubmit = async () => {
    setLoading(true); setError(""); setSuccess("");
    try {
      if (mode === "login") {
        const { data, error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        onAuth(data.user, data.session);
      } else {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setSuccess("Account created! Check your email to confirm, then log in.");
        setMode("login");
      }
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: "#f9f9f9", fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ background: "#fff", borderRadius: 16, padding: "2.5rem", width: 380,
        boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}>
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: "2rem" }}>
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#1D9E75" }} />
          <span style={{ fontSize: 20, fontWeight: 500 }}>OrbitGuard</span>
          <span style={{ fontSize: 12, color: "#888" }}>pass quality forecaster</span>
        </div>

        <h2 style={{ fontSize: 18, fontWeight: 500, marginBottom: "0.5rem" }}>
          {mode === "login" ? "Welcome back" : "Create account"}
        </h2>
        <p style={{ fontSize: 13, color: "#888", marginBottom: "1.5rem" }}>
          {mode === "login" ? "Sign in to your OrbitGuard account" : "Start forecasting satellite passes"}
        </p>

        {error && (
          <div style={{ background: "#FCEBEB", color: "#501313", borderRadius: 8,
            padding: "0.65rem 0.85rem", fontSize: 13, marginBottom: "1rem" }}>{error}</div>
        )}
        {success && (
          <div style={{ background: "#E1F5EE", color: "#085041", borderRadius: 8,
            padding: "0.65rem 0.85rem", fontSize: 13, marginBottom: "1rem" }}>{success}</div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={{ fontSize: 12, color: "#666", display: "block", marginBottom: 4 }}>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              onKeyDown={e => e.key === "Enter" && handleSubmit()}
              style={{ width: "100%", fontSize: 14, padding: "10px 12px", borderRadius: 8,
                border: "1px solid #ddd", outline: "none", boxSizing: "border-box" }} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: "#666", display: "block", marginBottom: 4 }}>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              onKeyDown={e => e.key === "Enter" && handleSubmit()}
              style={{ width: "100%", fontSize: 14, padding: "10px 12px", borderRadius: 8,
                border: "1px solid #ddd", outline: "none", boxSizing: "border-box" }} />
          </div>
          <button onClick={handleSubmit} disabled={loading || !email || !password}
            style={{ background: "#1D9E75", color: "#fff", border: "none", borderRadius: 8,
              padding: "11px", fontSize: 14, fontWeight: 500, cursor: "pointer",
              opacity: loading || !email || !password ? 0.6 : 1, marginTop: 4 }}>
            {loading ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </div>

        <div style={{ textAlign: "center", marginTop: "1.25rem", fontSize: 13, color: "#888" }}>
          {mode === "login" ? (
            <>Don't have an account?{" "}
              <span onClick={() => { setMode("signup"); setError(""); }}
                style={{ color: "#1D9E75", cursor: "pointer", fontWeight: 500 }}>Sign up</span>
            </>
          ) : (
            <>Already have an account?{" "}
              <span onClick={() => { setMode("login"); setError(""); }}
                style={{ color: "#1D9E75", cursor: "pointer", fontWeight: 500 }}>Sign in</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Ground Station Manager ─────────────────────────────────────────────────────

function StationManager({ userId, onSelect, currentLat, currentLon }) {
  const [stations, setStations] = useState([]);
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);

  const loadStations = useCallback(async () => {
    const { data } = await supabase
      .from("ground_stations")
      .select("*")
      .eq("user_id", userId)
      .order("created_at", { ascending: false });
    if (data) setStations(data);
  }, [userId]);

  useEffect(() => { loadStations(); }, [loadStations]);

  const saveStation = async () => {
    if (!name || !lat || !lon) return;
    setSaving(true);
    await supabase.from("ground_stations").insert({
      user_id: userId,
      name,
      lat: parseFloat(lat),
      lon: parseFloat(lon),
      created_at: new Date().toISOString(),
    });
    setName(""); setLat(""); setLon("");
    await loadStations();
    setSaving(false);
  };

  const deleteStation = async (id) => {
    await supabase.from("ground_stations").delete().eq("id", id);
    await loadStations();
  };

  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => setOpen(!open)}
        style={{ background: "#f5f5f5", border: "1px solid #e0e0e0", borderRadius: 8,
          padding: "6px 14px", fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}>
        📍 Ground stations {stations.length > 0 && `(${stations.length})`}
      </button>

      {open && (
        <div style={{ position: "absolute", top: "calc(100% + 8px)", right: 0, width: 320,
          background: "#fff", border: "1px solid #e0e0e0", borderRadius: 12,
          boxShadow: "0 8px 24px rgba(0,0,0,0.1)", zIndex: 200, padding: "1rem" }}>

          <div style={{ fontSize: 13, fontWeight: 500, marginBottom: "0.75rem" }}>Saved stations</div>

          {stations.length === 0 && (
            <div style={{ fontSize: 12, color: "#888", marginBottom: "0.75rem" }}>No stations saved yet.</div>
          )}

          {stations.map(s => (
            <div key={s.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "6px 0", borderBottom: "0.5px solid #f0f0f0" }}>
              <button onClick={() => { onSelect(s.lat, s.lon); setOpen(false); }}
                style={{ background: "none", border: "none", cursor: "pointer", textAlign: "left",
                  fontSize: 13, padding: 0 }}>
                <span style={{ fontWeight: 500 }}>{s.name}</span>
                <span style={{ color: "#888", marginLeft: 6, fontSize: 11 }}>{s.lat.toFixed(2)}, {s.lon.toFixed(2)}</span>
              </button>
              <button onClick={() => deleteStation(s.id)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#ccc", fontSize: 16, padding: "0 4px" }}>×</button>
            </div>
          ))}

          <div style={{ marginTop: "0.75rem", borderTop: "0.5px solid #f0f0f0", paddingTop: "0.75rem" }}>
            <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 6, color: "#555" }}>Add current location</div>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Station name"
              style={{ width: "100%", fontSize: 13, padding: "7px 10px", borderRadius: 6,
                border: "1px solid #ddd", marginBottom: 6, boxSizing: "border-box" }} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 6 }}>
              <input value={lat} onChange={e => setLat(e.target.value)} placeholder={`Lat: ${currentLat}`}
                style={{ fontSize: 13, padding: "7px 10px", borderRadius: 6, border: "1px solid #ddd" }} />
              <input value={lon} onChange={e => setLon(e.target.value)} placeholder={`Lon: ${currentLon}`}
                style={{ fontSize: 13, padding: "7px 10px", borderRadius: 6, border: "1px solid #ddd" }} />
            </div>
            <button onClick={() => { setLat(String(currentLat)); setLon(String(currentLon)); }}
              style={{ fontSize: 11, color: "#1D9E75", background: "none", border: "none",
                cursor: "pointer", padding: 0, marginBottom: 8 }}>
              ↑ Use current dashboard coordinates
            </button>
            <button onClick={saveStation} disabled={saving || !name || !lat || !lon}
              style={{ width: "100%", background: "#1D9E75", color: "#fff", border: "none",
                borderRadius: 6, padding: "7px", fontSize: 13, fontWeight: 500, cursor: "pointer",
                opacity: saving || !name || !lat || !lon ? 0.6 : 1 }}>
              {saving ? "Saving..." : "Save station"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────

function Dashboard({ user, apiKey, onLogout }) {
  const [noradId, setNoradId] = useState(25544);
  const [noradInput, setNoradInput] = useState("25544");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [showSearch, setShowSearch] = useState(false);
  const [lat, setLat] = useState(19.07);
  const [lon, setLon] = useState(72.87);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [inputMode, setInputMode] = useState("dropdown");

  const headers = { "Content-Type": "application/json", "X-Api-Key": apiKey };

  const fetchForecast = useCallback(async (id = noradId, fetchLat = lat, fetchLon = lon) => {
    setLoading(true); setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/passes/norad/${id}?lat=${fetchLat}&lon=${fetchLon}&hours_ahead=48&include_ionex=true`,
        { headers }
      );
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `API error ${res.status}`); }
      setData(await res.json());
    } catch (e) { setError(e.message); }
    setLoading(false);
  }, [noradId, lat, lon, apiKey]);

  useEffect(() => { if (apiKey) fetchForecast(); }, [apiKey]);

  const handleSearch = async (q) => {
    if (!q || q.length < 2) { setSearchResults([]); return; }
    try {
      const res = await fetch(`${API_BASE}/satellites/search?q=${encodeURIComponent(q)}`, { headers });
      if (res.ok) setSearchResults((await res.json()).results || []);
    } catch {}
  };

  const selectSat = (sat) => {
    setNoradId(sat.norad_id); setNoradInput(String(sat.norad_id));
    setSearchQuery(sat.name); setShowSearch(false); setSearchResults([]);
    fetchForecast(sat.norad_id);
  };

  const handleStationSelect = (newLat, newLon) => {
    setLat(newLat); setLon(newLon);
    fetchForecast(noradId, newLat, newLon);
  };

  const wx = data?.space_weather;
  const ionex = data?.ionospheric;
  const passes = data?.passes || [];
  const scores = passes.map(p => p.quality.score);
  const bestScore = scores.length ? Math.max(...scores) : null;
  const avoidCount = scores.filter(s => s < 20).length;
  const chartData = passes.map(p => ({
    time: new Date(p.aos).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false }),
    score: parseFloat(p.quality.score.toFixed(1)),
  }));

  return (
    <div style={{ padding: "1.25rem", fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
      maxWidth: 900, margin: "0 auto", color: "#111" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
        borderBottom: "0.5px solid #e0e0e0", paddingBottom: "0.75rem", marginBottom: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 18, fontWeight: 500 }}>
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#1D9E75" }} />
          OrbitGuard
          <span style={{ fontSize: 12, color: "#888", fontWeight: 400 }}>v2</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {wx && (
            <div style={{ position: "relative", display: "inline-block" }}
              onMouseEnter={e => e.currentTarget.querySelector(".wx-tooltip").style.display="block"}
              onMouseLeave={e => e.currentTarget.querySelector(".wx-tooltip").style.display="none"}>
              <span style={{ fontSize: 11, padding: "3px 8px", borderRadius: 6, fontWeight: 500, cursor: "help",
                background: wx.severity === "SEVERE" ? "#FCEBEB" : wx.severity === "MODERATE" ? "#FAEEDA" : wx.severity === "MINOR" ? "#FFF8E7" : "#E1F5EE",
                color: wx.severity === "SEVERE" ? "#501313" : wx.severity === "MODERATE" ? "#633806" : wx.severity === "MINOR" ? "#7A5200" : "#085041" }}>
                {wx.severity} {wx.g_scale && `(${wx.g_scale})`}
              </span>
              <div className="wx-tooltip" style={{ display: "none", position: "absolute", right: 0, top: "calc(100% + 6px)",
                background: "#1a1a1a", color: "#fff", fontSize: 12, padding: "8px 12px", borderRadius: 8,
                width: 260, zIndex: 999, lineHeight: 1.5, whiteSpace: "normal" }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>{wx.severity} — {wx.g_scale || "G0"}</div>
                <div style={{ color: "#ccc" }}>{wx.ops_impact || "Space weather conditions nominal."}</div>
              </div>
            </div>
          )}
          <StationManager userId={user.id} onSelect={handleStationSelect}
            currentLat={lat} currentLon={lon} />
          <div style={{ fontSize: 12, color: "#888" }}>{user.email}</div>
          <button onClick={onLogout}
            style={{ fontSize: 12, color: "#888", background: "none", border: "1px solid #e0e0e0",
              borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}>
            Sign out
          </button>
        </div>
      </div>

      {/* Space weather bar */}
      {wx && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "0.75rem 1rem",
          background: "#f5f5f5", borderRadius: 8, marginBottom: "1rem", flexWrap: "wrap" }}>
          {[["Kp index", wx.kp_index?.toFixed(1)], ["F10.7", wx.f107_solar_flux?.toFixed(0)],
            ["Alerts", wx.active_alert_count], ["Condition", wx.severity],
            ...(ionex ? [["TEC", `${ionex.vtec_tecu} TECU`], ["Ionosphere", ionex.condition]] : [])
          ].map(([lbl, val]) => (
            <div key={lbl} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, minWidth: 70 }}>
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

      {/* Ground station display */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "0.75rem",
        fontSize: 12, color: "#888" }}>
        📍 Ground station: <strong style={{ color: "#111" }}>{lat.toFixed(4)}° N, {lon.toFixed(4)}° E</strong>
        <span style={{ color: "#ccc" }}>|</span>
        <span>Change via "Ground stations" above or edit below</span>
      </div>

      {/* Controls */}
      <div style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          {["dropdown", "manual", "search"].map(mode => (
            <button key={mode} onClick={() => setInputMode(mode)}
              style={{ fontSize: 12, padding: "4px 12px", borderRadius: 20,
                border: "1px solid #ddd", cursor: "pointer",
                background: inputMode === mode ? "#1D9E75" : "#fff",
                color: inputMode === mode ? "#fff" : "#444" }}>
              {mode === "dropdown" ? "Popular sats" : mode === "manual" ? "Enter NORAD ID" : "Search by name"}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 10, alignItems: "end" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: "#888" }}>Satellite</label>
            {inputMode === "dropdown" && (
              <select value={noradId} onChange={e => setNoradId(Number(e.target.value))}
                style={{ fontSize: 14, padding: "6px 8px", borderRadius: 6, border: "1px solid #ddd" }}>
                {POPULAR_SATS.map(s => <option key={s.norad_id} value={s.norad_id}>{s.name}</option>)}
              </select>
            )}
            {inputMode === "manual" && (
              <input type="number" value={noradInput} placeholder="e.g. 44857"
                onChange={e => setNoradInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && (() => { const id = parseInt(noradInput); if (!isNaN(id)) { setNoradId(id); fetchForecast(id); } })()}
                style={{ fontSize: 14, padding: "6px 8px", borderRadius: 6, border: "1px solid #ddd" }} />
            )}
            {inputMode === "search" && (
              <div style={{ position: "relative" }}>
                <input value={searchQuery} placeholder="e.g. SENTINEL, ISS, NOAA"
                  onChange={e => { setSearchQuery(e.target.value); setShowSearch(true); handleSearch(e.target.value); }}
                  style={{ fontSize: 14, padding: "6px 8px", borderRadius: 6, border: "1px solid #ddd", width: "100%" }} />
                {showSearch && searchResults.length > 0 && (
                  <div style={{ position: "absolute", top: "100%", left: 0, right: 0,
                    background: "#fff", border: "1px solid #ddd", borderRadius: 6,
                    zIndex: 100, maxHeight: 180, overflowY: "auto", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }}>
                    {searchResults.map(s => (
                      <div key={s.norad_id} onClick={() => selectSat(s)}
                        style={{ padding: "8px 12px", cursor: "pointer", fontSize: 13, borderBottom: "0.5px solid #f0f0f0" }}
                        onMouseEnter={e => e.currentTarget.style.background = "#f5f5f5"}
                        onMouseLeave={e => e.currentTarget.style.background = "#fff"}>
                        <span style={{ fontWeight: 500 }}>{s.name}</span>
                        <span style={{ color: "#888", marginLeft: 8, fontSize: 11 }}>NORAD {s.norad_id}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
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
          <button onClick={() => {
            if (inputMode === "manual") {
              const id = parseInt(noradInput);
              if (!isNaN(id)) { setNoradId(id); fetchForecast(id); }
            } else fetchForecast();
          }} disabled={loading}
            style={{ background: "#1D9E75", color: "#fff", border: "none", borderRadius: 8,
              padding: "0 18px", height: 36, fontSize: 14, fontWeight: 500, cursor: "pointer" }}>
            {loading ? "Loading..." : "Forecast ↗"}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: "#FCEBEB", color: "#501313", borderRadius: 8,
          padding: "0.75rem 1rem", fontSize: 13, marginBottom: "1rem" }}>{error}</div>
      )}

      {ionex && (
        <div style={{ fontSize: 12, color: "#888", marginBottom: "0.75rem",
          padding: "6px 10px", background: "#f9f9f9", borderRadius: 6 }}>
          🌐 {ionex.note}
        </div>
      )}

      {/* Chart */}
      {chartData.length > 0 && (
        <div style={{ marginBottom: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.6rem" }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "#888", textTransform: "uppercase", letterSpacing: "0.06em" }}>Pass quality timeline</div>
          <div style={{ fontSize: 11, color: "#aaa" }}>Times in your local timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone})</div>
        </div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: -20 }}>
              <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#888" }} axisLine={false} tickLine={false} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#888" }} axisLine={false} tickLine={false} />
              <Tooltip formatter={v => [v.toFixed(1), "Score"]} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                {chartData.map((e, i) => <Cell key={i} fill={scoreColor(e.score)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Pass list */}
      <div style={{ fontSize: 13, fontWeight: 500, color: "#888", textTransform: "uppercase",
        letterSpacing: "0.06em", marginBottom: "0.6rem" }}>Upcoming pass windows</div>
      {loading ? (
        <div style={{ textAlign: "center", padding: "2rem", color: "#888", fontSize: 14 }}>Computing pass windows...</div>
      ) : passes.length === 0 && !error ? (
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

// ── Root App ───────────────────────────────────────────────────────────────────

export default function App() {
  const [user, setUser] = useState(null);
  const [apiKey, setApiKey] = useState(null);
  const [loading, setLoading] = useState(true);

  // Provision API key for user on first login
  const provisionApiKey = async (email) => {
    try {
      // Try to get existing key from Supabase user_metadata or register new one
      const res = await fetch(
        `${API_BASE}/keys/register?email=${encodeURIComponent(email)}&name=user`,
        { method: "POST" }
      );
      if (res.ok) {
        const data = await res.json();
        return data.api_key;
      }
    } catch (e) {
      console.error("API key provision failed:", e);
    }
    return process.env.REACT_APP_DEMO_API_KEY || "";
  };

  useEffect(() => {
    // Check existing session
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (session?.user) {
        setUser(session.user);
        const key = await provisionApiKey(session.user.email);
        setApiKey(key);
      }
      setLoading(false);
    });

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (session?.user) {
        setUser(session.user);
        const key = await provisionApiKey(session.user.email);
        setApiKey(key);
      } else {
        setUser(null);
        setApiKey(null);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const handleLogout = async () => {
    await supabase.auth.signOut();
    setUser(null);
    setApiKey(null);
  };

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "-apple-system, sans-serif", color: "#888", fontSize: 14 }}>
        Loading...
      </div>
    );
  }

  if (!user) {
    return <AuthPage onAuth={(u) => setUser(u)} />;
  }

  return <Dashboard user={user} apiKey={apiKey || process.env.REACT_APP_DEMO_API_KEY || ""} onLogout={handleLogout} />;
}
