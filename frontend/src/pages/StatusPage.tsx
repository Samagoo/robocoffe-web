// Platform status (Phase 1) + recent orders (GET /api/orders) for checking persistence.
import { useEffect, useState } from "react";
import { getJson, localTime } from "../api/http";
import type { Health, Order } from "../types";

const POLL_MS = 5000;

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  const color = ok === undefined ? "var(--muted)" : ok ? "var(--ok)" : "var(--bad)";
  return (
    <tr>
      <td>{label}</td>
      <td style={{ color }}>{value}</td>
    </tr>
  );
}

export default function StatusPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [h, o] = await Promise.all([getJson<Health>("/health"), getJson<Order[]>("/orders?limit=20")]);
        if (alive) (setHealth(h), setOrders(o), setError(null));
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const db = health?.database;
  return (
    <main>
      <h1>Platform status</h1>
      <p className="sub">Refreshes every 5 s</p>

      {error && <p className="error">Backend unreachable: {error}</p>}

      {health && db && (
        <table className="kv" style={{ marginBottom: 32 }}>
          <tbody>
            <Row label="Backend" value={`${health.status} (v${health.version})`} ok={health.status === "ok"} />
            <Row label="Database" value={db.status === "ok" ? `ok · ${db.db_time}` : `error · ${db.detail}`}
                 ok={db.status === "ok"} />
            <Row label="Schema revision" value={db.schema_revision ?? "none (migrations not applied)"}
                 ok={!!db.schema_revision} />
            <Row label="Robot link" value={`${health.robot.host}:${health.robot.port} · ${health.robot.link}`
                 + (health.robot.state ? ` · ${health.robot.state}` : "")} ok={health.robot.link === "connected"} />
            <Row label="Scale (Bluetooth)" value={health.scale.ingestion} />
            <Row label="Admin pages connected" value={String(health.realtime.admin_clients)} />
            <Row label="Server time (UTC)" value={health.time_utc} />
          </tbody>
        </table>
      )}

      <h2>Recent orders</h2>
      {orders.length === 0 ? (
        <p className="sub">No orders yet.</p>
      ) : (
        <table className="data">
          <thead>
            <tr><th>Folio</th><th>Product</th><th>Table</th><th>Name</th><th>Status</th><th>Ordered at</th></tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.folio}</td>
                <td>{o.product_code}</td>
                <td>{o.table_number}</td>
                <td>{o.customer_name ?? "—"}</td>
                <td>{o.status}</td>
                <td title={o.created_at}>{localTime(o.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
