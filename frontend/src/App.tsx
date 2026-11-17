// Phase 1: platform status page. Customer (/) and admin (/admin) pages arrive in Phases 2–3.
import { useEffect, useState } from "react";
import { getJson } from "./api/http";
import type { Health } from "./types";

const POLL_MS = 5000;

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  const color = ok === undefined ? "#666" : ok ? "#1a7f37" : "#c62828";
  return (
    <tr>
      <td style={{ padding: "6px 16px 6px 0", fontWeight: 600 }}>{label}</td>
      <td style={{ padding: "6px 0", color }}>{value}</td>
    </tr>
  );
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getJson<Health>("/health")
        .then((h) => alive && (setHealth(h), setError(null)))
        .catch((e: Error) => alive && setError(e.message));
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 640, margin: "48px auto", padding: 16 }}>
      <h1 style={{ marginBottom: 4 }}>RoboCoffee</h1>
      <p style={{ marginTop: 0, color: "#666" }}>Platform status · Phase 1</p>

      {error && <p style={{ color: "#c62828" }}>Backend unreachable: {error}</p>}

      {health && (
        <table style={{ borderCollapse: "collapse" }}>
          <tbody>
            <Row label="Backend" value={`${health.status} (v${health.version})`} ok={health.status === "ok"} />
            <Row
              label="Database"
              value={health.database.status === "ok" ? `ok · ${health.database.db_time}` : `error · ${health.database.detail}`}
              ok={health.database.status === "ok"}
            />
            <Row label="Robot link" value={`${health.robot.host}:${health.robot.port} · ${health.robot.link}`} />
            <Row label="Scale (Bluetooth)" value={health.scale.ingestion} />
            <Row label="Server time (UTC)" value={health.time_utc} />
          </tbody>
        </table>
      )}
    </main>
  );
}
