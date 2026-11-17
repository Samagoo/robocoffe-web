// Mirrors backend responses (backend/app/schemas.py and order_config.py).

export interface Health {
  status: "ok" | "degraded";
  version: string;
  time_utc: string;
  database: { status: "ok" | "error"; db_time?: string; schema_revision?: string | null; detail?: string };
  robot: { host: string; port: number; link: string; state: string | null };
  scale: { ingestion: string };
  realtime: { admin_clients: number };
}

// ---- WebSocket /api/ws/admin (docs/websocket.md). Envelope: {type, ts (UTC ISO), data}
export type ServerMessage =
  | { type: "hello"; ts: string; data: { version: string; snapshot_limit: number } }
  | { type: "snapshot"; ts: string; data: { orders: Order[] } }
  | { type: "order.created"; ts: string; data: Order }
  | { type: "order.updated"; ts: string; data: Order }
  | { type: "robot.status"; ts: string; data: RobotStatus }
  | { type: "pong"; ts: string; data: Record<string, never> }
  | { type: "error"; ts: string; data: { detail: string } };

export type FeedStatus = "connecting" | "live" | "reconnecting";

export interface Product {
  code: string;
  name: string;
}

export interface Table {
  number: number;
  robot_destination: string;
  distance_m: number;
}

export interface Catalog {
  products: Product[];
  tables: Table[];
  statuses: string[]; // provisional names, from order_config.json
  initial_status: string;
  dispatch_from: string[];
  dispatched_status: string;
}

// GET /api/robot and WebSocket "robot.status" (from ClienteRobot.resumen())
export interface RobotStatus {
  host: string;
  port: number;
  link: "connected" | "disconnected" | "unavailable";
  state: string | null;          // robot FSM state: ESPERANDO_ORDEN, RECORRIDO_MESA_2, EN_MESA, ...
  robot_order: number | null;    // = Order.robot_msg_id of the current trip
  battery_v: number | null;
  pose: { x: number; y: number; th: number } | null;
  error: string | null;
  free: boolean;                 // connected and ESPERANDO_ORDEN
  last_message_at: string | null;
}

// POST /api/orders/{id}/dispatch (200 / 409 / 504 share this body; 503/404 use {detail})
export interface DispatchResult {
  ok: boolean;
  robot_msg_id: number;
  reason: string;
  robot_state: string | null;
  order: Order;
}

export interface OrderCreate {
  product_code: string;
  table_number: number;
  customer_name?: string | null;
  notes?: string | null;
}

export interface Order {
  id: number;
  folio: string;
  product_code: string;
  table_number: number;
  distance_m: number;
  customer_name: string | null;
  notes: string | null;
  status: string;
  incident: string | null;
  load_weight_g: number | null;
  delivery_weight_g: number | null;
  robot_msg_id: number | null;
  created_at: string; // ISO 8601, UTC
  updated_at: string;
  ready_at: string | null;
  dispatched_at: string | null;
  arrived_at: string | null;
  delivered_at: string | null;
  returned_at: string | null;
}
