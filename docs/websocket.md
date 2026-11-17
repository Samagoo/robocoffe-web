# WebSocket protocol: `/api/ws/admin`

Live feed for the admin page. JSON text frames. Through the Vite dev server:
`ws://localhost:5173/api/ws/admin`. Directly on the backend: `ws://localhost:8000/api/ws/admin`.

## Envelope (server → client)

```json
{ "type": "order.created", "ts": "2026-11-17T09:33:35.701+00:00", "data": { … } }
```

`ts` is when the server **sent** the message (UTC). Business timestamps (`created_at`, …) are inside `data`.

## Server → client

| `type` | When | `data` |
|---|---|---|
| `hello` | Right after connecting | `{version, snapshot_limit}` |
| `snapshot` | Right after `hello` | `{orders: Order[]}`: newest 100, same shape as `GET /api/orders` |
| `robot.status` | Right after `snapshot`; then when it changes, at least every 5 s | `RobotStatus`: same as `GET /api/robot` (see `robot-integration.md`) |
| `order.created` | After a new order is **committed** | `Order` |
| `order.updated` | After an order changes: dispatch accepted, rejected or unanswered (Phase 4) | `Order` |
| `pong` | Reply to `ping` | `{}` |
| `error` | Client sent something unknown | `{detail}` |

`Order` is exactly the `OrderOut` JSON from the REST API.

## Client → server

| `type` | Purpose |
|---|---|
| `ping` | Keep-alive (the admin page sends one every 25 s) |

## Client rules (implemented in `frontend/src/api/ws.ts`)

1. **Merge, don't replace.** Keep a map by `id`. For each order received, keep the one with the newest `updated_at`.
   Duplicates (the same order in `snapshot` and `order.created`) are expected and harmless.
2. **Reconnect** with backoff (1 s, doubling, max 10 s). Every reconnection gets a fresh `snapshot`,
   so updates missed while disconnected are recovered. There's no replay of individual messages.
3. Ignore unknown `type`s, so new message types don't break old pages.
4. While disconnected, treat the robot status as unknown. A fresh `robot.status` comes with every reconnection.

## Server rules

- Broadcast **only after the DB commit**, so an admin never sees an order that isn't stored.
- Connections are kept in memory, in **one backend process**. Several uvicorn workers would each
  see only their own clients, which is fine for a single Windows PC.
- A client that fails or takes > 5 s to receive is dropped. Its page reconnects by itself.
- No authentication yet (same as the robot's TCP port 9000).
