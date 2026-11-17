// Robot status from ClienteRobot (via WebSocket "robot.status").
import type { Order, RobotStatus } from "../types";

const LINK: Record<RobotStatus["link"], { text: string; color: string }> = {
  connected: { text: "● Connected", color: "var(--ok)" },
  disconnected: { text: "● Disconnected", color: "var(--bad)" },
  unavailable: { text: "● Client unavailable", color: "var(--bad)" },
};

function ago(iso: string | null, now: number): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  return s < 2 ? "just now" : `${s} s ago`;
}

export default function RobotPanel({ robot, orders, now }: { robot: RobotStatus | null; orders: Order[]; now: number }) {
  if (!robot) {
    return <div className="card robot-panel"><strong>Robot</strong> <span className="sub">waiting for status…</span></div>;
  }
  const link = LINK[robot.link];
  const trip = robot.robot_order != null ? orders.find((o) => o.robot_msg_id === robot.robot_order) : undefined;
  const p = robot.pose;
  return (
    <div className="card robot-panel" data-testid="robot-panel">
      <div className="robot-grid">
        <div><small>Robot software</small><span style={{ color: link.color, fontWeight: 600 }}>{link.text}</span>
          <small>{robot.host}:{robot.port}</small></div>
        <div><small>State</small><strong data-testid="robot-state">{robot.state ?? "—"}</strong>
          {robot.error && <span style={{ color: "var(--bad)" }}>{robot.error}</span>}</div>
        <div><small>Current order</small><strong>{trip ? trip.folio : robot.robot_order ?? "—"}</strong>
          {trip && <small>Table {trip.table_number}</small>}</div>
        <div><small>Battery</small><strong>{robot.battery_v != null ? `${robot.battery_v.toFixed(2)} V` : "—"}</strong></div>
        <div><small>Pose (x, y, θ)</small>
          <strong>{p ? `${p.x.toFixed(2)} m, ${p.y.toFixed(2)} m, ${p.th.toFixed(0)}°` : "—"}</strong></div>
        <div><small>Last message</small><span>{ago(robot.last_message_at, now)}</span></div>
      </div>
    </div>
  );
}
