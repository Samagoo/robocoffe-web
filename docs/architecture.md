# RoboCoffee platform — MVP architecture

Single Windows PC. Out of scope for now: multi-computer, analytics, cloud.

## Decisions (approved 17 Nov 2026)

1. **The robot subsystem is external and stays intact** in `robot/`. The platform talks to it only
   through the existing TCP line protocol on port 9000. It runs natively, not in Docker.
2. **The Bluetooth load cell is part of the MVP architecture.** It is read by `scale_bridge/`, a native process,
   because containers can't open Windows COM ports. The backend interface is reserved from the start.
3. **Robot dispatch is part of the MVP.** First end-to-end milestone:
   customer places order → admin sees it → admin dispatches → `main_real` receives `ORDEN` → robot moves.
4. **Order-state names are not standardized yet.** Statuses are stored as text, and the allowed statuses,
   transitions and robot-event → status mapping are loaded from a config file, not hard-coded.
5. **Robot events are persisted separately** in `robot_events`, apart from `order_events`.

## Runtime layout

| Process | Where | Port |
|---|---|---|
| PostgreSQL 16 | Docker | 5432 |
| FastAPI backend | Docker | 8000 |
| React + Vite dev server | Docker | 5173 (proxies `/api` → backend) |
| `robot/main_real.py` or `servidor_simulado.py` | Windows, native | 9000 |
| `scale_bridge/` | Windows, native | COM port → HTTP to 8000 |

## Planned tables

All timestamps are `timestamptz`, stored in UTC and set by the backend on receipt.

| Table | Purpose | Phase |
|---|---|---|
| `orders` | One row per order: table number, `status` (text, configurable), robot message id, key timestamps | 2 |
| `order_events` | Every order status change: from, to, cause, source, timestamp | 2 |
| `robot_events` | Every `EVT` line from the robot: type, raw line, parsed fields (JSONB), order id if any, timestamp | 2 (schema) / 4 (filled) |
| `scale_readings` | Load-cell readings from the bridge | 2 (schema) / scale phase (filled) |

## Robot-link rules inherited from `fsm.py`

- **One order at a time.** The robot replies `ERROR ORDEN … OCUPADO` otherwise. The queue lives in the backend.
- **Message ids must always increase** (`ID_REPETIDO` otherwise). The backend uses millisecond timestamps
  so ids keep increasing across backend restarts.
- `ESTADO` / `PING` are always answered and never change state, so they're safe for health checks.

## Phases

| # | Delivers | Done when |
|---|---|---|
| 1 | Docker Compose (db, backend, frontend), `/api/health`, status page | `docker compose up` → page shows DB ok |
| 2 | All four tables, configurable order workflow, `POST/GET /api/orders`, customer page | An order placed on the page is in PostgreSQL |
| 3 | WebSocket `/api/ws/admin`, admin page | A new order appears on the admin page without a refresh |
| 4 | Robot TCP link, dispatch endpoint, `EVT` → `robot_events` | **Milestone:** dispatch → `main_real` receives `ORDEN` → robot moves |
| 5 | Scale bridge + `/api/scale/readings`, `RETIRADO` forwarding | A cup lift on the adapter ends the wait at the table |
| 6 | Order status driven by robot events (once the workflow is approved) | The admin page follows the robot's trip live |
