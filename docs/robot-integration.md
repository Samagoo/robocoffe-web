# Robot integration (Phase 4)

The platform talks to the robot software **only** through the robot team's `ClienteRobot`
(`robot/cliente/robocoffe_cliente.py`), imported **unchanged**. No other TCP code exists in the
platform. Robot code, firmware and the ESP32 are not modified.

```
admin page ──POST /api/orders/{id}/dispatch──► backend RobotLink ──ClienteRobot.ordenar()──► :9000
                                                   ▲                                   main_real.py
admin page ◄──WS robot.status / order.updated──────┤◄── ClienteRobot.suscribir() queue ◄── EVT / OK / ERROR
                                                   └──► robot_events (every EVT, UTC receive time)
```

## How the backend gets `ClienteRobot`

`docker-compose.yml` mounts `${ROBOT_CLIENT_HOST_DIR:-./robot/cliente}` read-only at
`/code/robot_cliente`, and `app/robot/link.py` imports `robocoffe_cliente` from there.
If the file isn't found, the backend still runs. `/api/robot` then shows `link: "unavailable"`.

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ROBOT_HOST` / `ROBOT_PORT` | `host.docker.internal` / `9000` | Where `main_real.py` or `servidor_simulado.py` listens (same PC) |
| `ROBOT_CLIENT_HOST_DIR` | `./robot/cliente` | Folder with `robocoffe_cliente.py` |
| `ROBOT_POLL_S` | `2` | Seconds between `ESTADO` queries, for a live pose (`LATIDO` carries none). `0` = off |
| `ROBOT_ENABLED` | `true` | `false` = don't connect (tests) |

`CanalTCP` accepts at most **4 clients**. The backend uses one. `consola_ordenes.py` or `nc` use one each.

## Dispatch (`POST /api/orders/{id}/dispatch`)

1. The order must be in `dispatch_from` (`order_config.json`) and not yet dispatched (otherwise **409**).
   The robot software must be connected (otherwise **503**).
2. `id = ClienteRobot.nuevo_id()` is written to `orders.robot_msg_id` **before** sending, so robot
   events that arrive before the OK can already be linked.
3. `ClienteRobot.ordenar(table, id_=id)` sends `ORDEN id=<id> destino=MESA<n>`. ClienteRobot retries
   with the **same id**, so the robot never starts twice.
4. The outcome:

| Robot answer | HTTP | Order |
|---|---|---|
| `OK ORDEN` | 200 | `dispatched_at` = moment ORDEN was sent, status → `dispatched_status` |
| `ERROR ORDEN <code>` (`OCUPADO`, `FUERA_DE_BASE`, `SIN_ENLACE_ROBOT`, `BATERIA_BAJA`, `EN_ERROR`) | 409 | unchanged; `robot_msg_id` cleared; `order_events` row `dispatch_rejected:<code>` |
| no answer after 3 tries | 504 | backend asks `ESTADO`: if the robot is carrying this id → treated as 200; else unchanged, can be dispatched again |

The robot remains the authority. The platform doesn't pre-judge whether the robot is free, at
base or charged; the robot's own guards (`fsm.py`) decide.

**A lost OK can't lose a trip.** `EVT TRANSICION a=RECORRIDO_MESA_n orden=<id>` also confirms the
dispatch (`order_events` cause `confirmed_by_robot_event`). The OK and that event arrive in the
same robot cycle, so whichever is processed first wins. It never counts twice.

## Robot events (`robot_events`)

- Every `EVT` line (`TRANSICION`, `LLEGO`, `TRAMO`, `ERROR`, `LATIDO`) is stored with
  `received_at` (UTC, platform clock), `robot_t` (the robot's `t=`), all fields as JSONB and the raw line.
- `robot_msg_id` = the line's `orden=`. `order_id` is filled when it matches an order.
- `CONEXION` rows are written by the **platform** when the link to the robot software goes up or
  down (`raw` starts with `[platform]`). Use them for downtime analysis.
- `LATIDO` arrives every 1 s, so about 3,600 rows per hour of operation. That's fine for PostgreSQL.
  Filter them out (`event_type <> 'LATIDO'`) when you look at a trip.
- `OK`/`ERROR` replies are not stored here. Their outcome is in `order_events`.

## Robot status (`GET /api/robot`, WebSocket `robot.status`)

From `ClienteRobot.resumen()`: `link` (connected / disconnected / unavailable), `state`,
`robot_order` (= `robot_msg_id` of the current trip), `battery_v`, `pose {x, y, th}`, `error`,
`free`, plus `last_message_at` (UTC). Sent to admin pages when it changes, and at least every 5 s.

## Not in Phase 4

- Order status after dispatch (arrival, delivery, return) is **not** derived from events yet.
  It waits for the approved workflow. The events are all in `robot_events`, so these timestamps
  can be filled afterwards. `SeguimientoPedidos` in `robocoffe_cliente.py` already has the
  incident rules for that phase.
- `RETIRADO`, `CANCELAR`, `PAUSA`, `RESET` buttons and the scale come in later phases.
