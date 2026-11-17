// All REST calls go to /api, which Vite proxies to the backend.

/** Turns FastAPI error bodies ({detail: string | [{msg}]}) into a readable message. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail))
      return body.detail.map((d: { msg?: string }) => d.msg?.replace(/^Value error, /, "")).join("; ");
  } catch {
    /* not JSON */
  }
  return `${res.status} ${res.statusText}`;
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return (await res.json()) as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return (await res.json()) as T;
}

/** POST /api/orders/{id}/dispatch. Returns the HTTP status and body; never throws for 4xx/5xx. */
export async function dispatchOrder(orderId: number): Promise<{ status: number; body: any }> {
  const res = await fetch(`/api/orders/${orderId}/dispatch`, { method: "POST" });
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    /* empty */
  }
  return { status: res.status, body };
}

/** UTC ISO timestamp -> local date/time of this computer, e.g. 17/11/2026, 03:41:20 */
export function localTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("es-MX", { hour12: false }) : "—";
}
