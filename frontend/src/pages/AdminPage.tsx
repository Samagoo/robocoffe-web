// Admin: live order list over WebSocket + robot status + Dispatch (sends ORDEN via ClienteRobot).
import { useEffect, useState } from "react";
import { dispatchOrder, getJson, localTime } from "../api/http";
import { useOrdersFeed } from "../api/ws";
import RobotPanel from "../components/RobotPanel";
import type { Catalog, FeedStatus, Order, RobotStatus } from "../types";

const BADGE: Record<FeedStatus, { text: string; color: string }> = {
  connecting: { text: "Connecting…", color: "var(--muted)" },
  live: { text: "● Live", color: "var(--ok)" },
  reconnecting: { text: "● Reconnecting…", color: "var(--bad)" },
};

// Robot reason codes (fsm.py / ClienteRobot) -> short text for the operator
const REASONS: Record<string, string> = {
  OCUPADO: "robot is busy with another order",
  FUERA_DE_BASE: "robot is not at the base",
  SIN_ENLACE_ROBOT: "robot software has no link to the OAK9",
  BATERIA_BAJA: "battery too low",
  EN_ERROR: "robot is in ERROR (move it to the base and RESET)",
  SIN_RESPUESTA: "no answer — if the robot starts moving it will be confirmed, otherwise dispatch again",
};

type Note = { ok: boolean; text: string };

function waited(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function dispatchBlocker(o: Order, catalog: Catalog | null, robot: RobotStatus | null): string | null {
  if (o.dispatched_at) return "already dispatched";
  if (!catalog?.dispatch_from.includes(o.status)) return `status ${o.status}`;
  if (!robot || robot.link !== "connected") return "robot not connected";
  if (!robot.free) return `robot is ${robot.state ?? "busy"}`;
  return null;
}

export default function AdminPage() {
  const { orders, status, newIds, robot } = useOrdersFeed();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [filter, setFilter] = useState<string>("ALL");
  const [now, setNow] = useState(Date.now());
  const [sending, setSending] = useState<number | null>(null);
  const [notes, setNotes] = useState<Record<number, Note>>({});

  useEffect(() => {
    getJson<Catalog>("/catalog").then(setCatalog).catch(() => setCatalog(null));
    const t = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(t);
  }, []);

  async function dispatch(o: Order) {
    setSending(o.id);
    const { status: code, body } = await dispatchOrder(o.id).catch(() => ({ status: 0, body: null }));
    let note: Note;
    if (code === 200) note = { ok: true, text: `Sent · robot ${body.robot_state ?? ""}` };
    else if (body?.reason) note = { ok: false, text: `${body.reason}: ${REASONS[body.reason] ?? "rejected"}` };
    else note = { ok: false, text: body?.detail ?? `request failed (${code || "network"})` };
    setNotes((n) => ({ ...n, [o.id]: note }));
    setSending(null);
  }

  const productName = (code: string) => catalog?.products.find((p) => p.code === code)?.name ?? code;
  const shown = filter === "ALL" ? orders : orders.filter((o) => o.status === filter);
  const badge = BADGE[status];

  return (
    <main style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
        <h1>Orders</h1>
        <span style={{ color: badge.color, fontWeight: 600 }} data-testid="feed-status">{badge.text}</span>
      </div>
      <p className="sub">New orders appear automatically. Dispatch sends the order to the robot (ORDEN).</p>

      <RobotPanel robot={robot} orders={orders} now={now} />

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
              <th>Status</th><th>Ordered at</th><th>Waiting</th><th>Robot</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((o) => {
              const blocker = dispatchBlocker(o, catalog, robot);
              const note = notes[o.id];
              return (
                <tr key={o.id} className={newIds.has(o.id) ? "new-row" : undefined}>
                  <td><strong>{o.folio}</strong></td>
                  <td>{o.product_code} · {productName(o.product_code)}</td>
                  <td>{o.table_number}</td>
                  <td>{o.customer_name ?? "—"}</td>
                  <td>{o.notes ?? "—"}</td>
                  <td>{o.status}</td>
                  <td title={o.created_at}>{localTime(o.created_at)}</td>
                  <td>{o.dispatched_at ? "—" : waited(o.created_at, now)}</td>
                  <td style={{ minWidth: 190 }}>
                    {o.dispatched_at ? (
                      <span className="note ok" title={o.dispatched_at}>Dispatched {localTime(o.dispatched_at).split(", ")[1]}</span>
                    ) : (
                      <button className="primary small" disabled={!!blocker || sending !== null}
                              title={blocker ?? "Send ORDEN to the robot"} onClick={() => dispatch(o)}>
                        {sending === o.id ? "Sending…" : "Dispatch"}
                      </button>
                    )}
                    {note && !o.dispatched_at && <div className={`note ${note.ok ? "ok" : "bad"}`}>{note.text}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </main>
  );
}
