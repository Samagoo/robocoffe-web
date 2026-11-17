// Mirrors backend responses. Order types arrive in Phase 2.

export interface Health {
  status: "ok" | "degraded";
  version: string;
  time_utc: string;
  database: { status: "ok" | "error"; db_time?: string; detail?: string };
  robot: { host: string; port: number; link: string };
  scale: { ingestion: string };
}
