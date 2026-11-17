// Adapter weight, live (Phase 5.1). Display only: no decisions are taken from it yet.
import { useEffect, useMemo, useState } from "react";
import { getJson } from "../api/http";
import type { ScaleReading, ScaleStatus } from "../types";

const WINDOW_S = 60;
const LINK: Record<ScaleStatus["link"], { text: string; color: string }> = {
  live: { text: "● Live", color: "var(--ok)" },
  stale: { text: "● No data", color: "var(--bad)" },
  port_closed: { text: "● Port closed", color: "var(--bad)" },
  offline: { text: "● Bridge offline", color: "var(--muted)" },
};
// Reference lines from the paper (m_on / m_off). Shown for context only in 5.1.
const LINES = [
  { g: 150, label: "150 g" },
  { g: 50, label: "50 g" },
];

/** HH:MM:SS.mmm in this computer's local time (real timestamps matter here). */
function clock(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("es-MX", { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

export default function ScalePanel({ scale, live, now }: { scale: ScaleStatus | null; live: ScaleReading[]; now: number }) {
  const [history, setHistory] = useState<ScaleReading[]>([]);

  // Seed the chart with the last minute from the DB; live readings are appended by the WebSocket.
  useEffect(() => {
    getJson<ScaleReading[]>(`/scale/readings?seconds=${WINDOW_S}`).then(setHistory).catch(() => setHistory([]));
  }, [scale?.source]);

  const points = useMemo(() => {
    const byTime = new Map<string, ScaleReading>();
    [...history, ...live].forEach((r) => byTime.set(r.received_at, r));
    const since = now - WINDOW_S * 1000;
    return [...byTime.values()]
      .filter((r) => Date.parse(r.received_at) >= since && (!scale?.source || r.source === scale.source))
      .sort((a, b) => (a.received_at < b.received_at ? -1 : 1));
  }, [history, live, now, scale?.source]);

  const link = scale ? LINK[scale.link] : { text: "waiting…", color: "var(--muted)" };
  const last = scale?.last_reading;
  const fresh = scale?.link === "live";

  // chart geometry
  const W = 600, H = 150, PAD = 4;
  const vals = points.map((p) => p.grams);
  const yMax = Math.max(400, ...vals), yMin = Math.min(-60, ...vals);
  const x = (iso: string) => PAD + ((Date.parse(iso) - (now - WINDOW_S * 1000)) / (WINDOW_S * 1000)) * (W - 2 * PAD);
  const y = (g: number) => PAD + (1 - (g - yMin) / (yMax - yMin)) * (H - 2 * PAD);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.received_at).toFixed(1)},${y(p.grams).toFixed(1)}`).join(" ");

  return (
    <div className="card scale-panel" data-testid="scale-panel">
      <div className="scale-head">
        <div>
          <small>Adapter weight</small>
          <div className="scale-weight" data-testid="scale-weight" style={{ opacity: fresh ? 1 : 0.4 }}>
            {last ? `${last.grams.toFixed(1)} g` : "— g"}
          </div>
        </div>
        <div className="scale-meta">
          <span style={{ color: link.color, fontWeight: 600 }} data-testid="scale-link">{link.text}</span>
          <small>{scale?.source ?? "no bridge"}{scale?.detail ? ` · ${scale.detail}` : ""}</small>
          <small>
            Last reading: {last ? `${clock(last.received_at)} (${scale?.age_s?.toFixed(1)} s ago)` : "never"}
          </small>
          <small>
            Received {scale?.readings_received ?? 0}
            {scale?.bridge_counters?.invalid ? ` · ${scale.bridge_counters.invalid} invalid lines` : ""}
            {scale?.bridge_queued ? ` · ${scale.bridge_queued} queued in bridge` : ""}
          </small>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="Weight, last 60 seconds">
        <line x1={PAD} x2={W - PAD} y1={y(0)} y2={y(0)} stroke="var(--line)" />
        {LINES.map((l) => (
          <g key={l.g}>
            <line x1={PAD} x2={W - PAD} y1={y(l.g)} y2={y(l.g)} stroke="var(--muted)" strokeDasharray="4 4" strokeWidth={0.8} />
            <text x={W - PAD - 2} y={y(l.g) - 3} fontSize="10" textAnchor="end" fill="var(--muted)">{l.label}</text>
          </g>
        ))}
        <path d={path} fill="none" stroke="var(--coffee)" strokeWidth={1.8} />
        {points.length > 0 && (
          <circle cx={x(points[points.length - 1].received_at)} cy={y(points[points.length - 1].grams)} r={3} fill="var(--coffee)" />
        )}
      </svg>
      <small className="sub">Last {WINDOW_S} s · dashed lines: thresholds from the paper (not used yet)</small>
    </div>
  );
}
