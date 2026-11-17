// Admin: live order list over WebSocket. Dispatch arrives in Phase 4.
import { useEffect, useState } from "react";
import { getJson, localTime } from "../api/http";
import { useOrdersFeed } from "../api/ws";
import type { Catalog, FeedStatus } from "../types";

const BADGE: Record<FeedStatus, { text: string; color: string }> = {
  connecting: { text: "Connecting…", color: "var(--muted)" },
  live: { text: "● Live", color: "var(--ok)" },
  reconnecting: { text: "● Reconnecting…", color: "var(--bad)" },
};

function waited(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export default function AdminPage() {
  const { orders, status, newIds } = useOrdersFeed();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [filter, setFilter] = useState<string>("ALL");
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    getJson<Catalog>("/catalog").then(setCatalog).catch(() => setCatalog(null));
    const t = window.setInterval(() => setNow(Date.now()), 5_000);
    return () => window.clearInterval(t);
  }, []);

  const productName = (code: string) => catalog?.products.find((p) => p.code === code)?.name ?? code;
  const shown = filter === "ALL" ? orders : orders.filter((o) => o.status === filter);
  const badge = BADGE[status];

  return (
    <main style={{ maxWidth: 1000 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
        <h1>Orders</h1>
        <span style={{ color: badge.color, fontWeight: 600 }} data-testid="feed-status">{badge.text}</span>
      </div>
      <p className="sub">New orders appear automatically. Dispatch to the robot arrives in Phase 4.</p>

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <label htmlFor="filter" style={{ margin: 0 }}>Status</label>
        <select id="filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="ALL">All</option>
          {catalog?.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="sub" style={{ margin: 0 }}>{shown.length} order(s)</span>
      </div>

      {shown.length === 0 ? (
        <p className="sub">{status === "live" ? "No orders." : "Waiting for the server…"}</p>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>Folio</th><th>Product</th><th>Table</th><th>Name</th><th>Notes</th>
              <th>Status</th><th>Ordered at</th><th>Waiting</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((o) => (
              <tr key={o.id} className={newIds.has(o.id) ? "new-row" : undefined}>
                <td><strong>{o.folio}</strong></td>
                <td>{o.product_code} · {productName(o.product_code)}</td>
                <td>{o.table_number}</td>
                <td>{o.customer_name ?? "—"}</td>
                <td>{o.notes ?? "—"}</td>
                <td>{o.status}</td>
                <td title={o.created_at}>{localTime(o.created_at)}</td>
                <td>{waited(o.created_at, now)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
