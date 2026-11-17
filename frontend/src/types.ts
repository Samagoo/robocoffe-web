// Mirrors backend responses (backend/app/schemas.py and order_config.py).

export interface Health {
  status: "ok" | "degraded";
  version: string;
  time_utc: string;
  database: { status: "ok" | "error"; db_time?: string; schema_revision?: string | null; detail?: string };
  robot: { host: string; port: number; link: string };
  scale: { ingestion: string };
}

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
