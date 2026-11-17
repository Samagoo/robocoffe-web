# Phase 5 — Automatic pickup detection (HX711 + Bluetooth → RETIRADO)

Status: **5.1 implemented** (ingestion, see `scale_bridge/README.md`); 5.2+ designed · updated 17 Nov 2026

**Fixed constraints (17 Nov):** the adapter firmware is deployed and won't change. It sends only `PESO:<g>`: no frame counter, no voltage, no time, no order or robot data. The adapter and the robot are independent systems. Every timestamp is the PC's, on reception. All decisions are made in the backend. The robot FSM is unchanged and uses the validated `RETIRADO` path.

**Goal:** when the customer takes the cup at the table, the robot returns to base by itself,
with no manual `RETIRADO`. A false `RETIRADO` must never happen, because the robot would drive
away while the cup is still on it or a hand is near.

---

## 0. What already exists (reused, not rebuilt)

| Piece | Where | State |
|---|---|---|
| Adapter: Nano + HX711 (10 SPS) + HC-05 (SoftwareSerial D10/D11, 9600 baud), frame `PESO:<g>` about every 0.6 s | Paper Table VIII, Fig. 4 | **Bench-tested**; real log 17 Nov in `scale_bridge/samples/` |
| Thresholds m_on = 150 g (placed), m_off = 50 g (removed), δ = 10 g portion tolerance, Δm = 5 g transit loss, tare before each order | Paper Table II, Eq. (7) | Designed |
| `EN_MESA` → `REGRESO_BASE` on `RETIRADO` (TCP) or on `t_entrega` | `fsm.py` T10 | **Validated on the real robot** |
| `ClienteRobot.retirado()` | `robocoffe_cliente.py` | Exists, used unchanged |
| `scale_readings` table; `orders.load_weight_g`, `delivery_weight_g`, `delivered_at` | Migration 0001 | Exists, empty |
| `scale_bridge/` (reserved) | Repo | Folder + README only |

**There are no changes to `fsm.py`, `main_real.py`, `oak9lib` or the OAK9's ESP32 firmware.**

---

## 1. Architecture

```
 ┌──────────── adapter on the robot ────────────┐
 │ load cell → HX711 → Nano ── HC-05 ~~BT SPP~~ │
 └───────────────────────────────────────────────┘
                     │  "PESO:352.4\n" every ~0.6 s
                     ▼
 Windows PC ─ COMx (BT serial port, "outgoing")
   │
   ├─ scale_bridge.py  (native Python + pyserial; NEW, ~150 lines)
   │     stamps UTC on reception, POST /api/scale/readings
   │
   ├─ Docker: FastAPI backend
   │     AdapterFSM (NEW, pure logic, like fsm.py) ── debounce + interlocks
   │     └─ decision "pickup confirmed" ─► RobotLink ─► ClienteRobot.retirado()
   │                                                         │ "RETIRADO id=…"
   └─ main_real.py (UNCHANGED) ◄──────────── TCP :9000 ──────┘
         EN_MESA ─T10─► REGRESO_BASE  (fallback: t_entrega = 180 s)
```

### Why the decision runs in the backend

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Bridge → backend → `RETIRADO` via ClienteRobot** | No robot code changes. The path is already validated on hardware. The backend knows the order, robot state and table. Weights are stored for the dashboard. Thresholds change without reflashing. One place to test. | Two more hops (about 50–100 ms total, small next to the 0.6 s frame). If the backend is down, there's no auto pickup. | **Recommended** |
| B. `main_real.py` reads COM itself → `fuente_vaso` → `Lecturas.vaso_retirado` (hook already exists in `Ejecutor`) | Fewest hops. Works without the backend. | Modifies `main_real.py`. Only one process can open the COM port, so the platform loses the weights unless the protocol is extended. The decision has no order context. | Fallback only |
| C. Decision in the adapter firmware | Lowest latency | Firmware has no robot state, no order, no clock. Every tuning needs a reflash. Hard to test. | No |

**If the backend is down, it fails safe:** no `RETIRADO` is sent, and the robot still returns by
`t_entrega` (180 s in operation). That's exactly today's behaviour, so automatic pickup can only *shorten* the wait.

### About "ESP32"

The adapter documented in the paper is a **Nano + HC-05**. The OAK9's ESP32 is not touched. If the
adapter moves to an ESP32, use **Bluetooth Classic SPP** (`BluetoothSerial`). It still appears as a COM
port and nothing else in this design changes. **Avoid BLE**: Windows doesn't expose BLE as a COM port,
so the bridge would need a different library (`bleak`).

---

## 2. State machines

### 2.1 Robot FSM (`fsm.py`): no change

`EN_MESA` already accepts `RETIRADO` (and `vaso_retirado`), and `t_entrega` stays as the safety
fallback. A `RETIRADO` that arrives in any other state is answered `NO_PERMITIDO` by the robot, so it is harmless.

### 2.2 Adapter FSM (NEW, backend: `app/adapter/fsm.py`)

Built like `fsm.py`: **one state variable, `cambiar()` is the only place it changes, nothing blocks,
times are measured from state entry, every transition is logged, and failures are states.** Inputs on each step:
the latest weight frame (or none), the robot state and current order from `ClienteRobot`, and the time.
Outputs: actions (`SEND_RETIRADO`, `RECORD_LOAD_WEIGHT`, `RECORD_DELIVERY_WEIGHT`, `INCIDENT`) and transition events.

States (names follow `state_machine_notes.txt`, plus three needed for safety):

| State | Meaning |
|---|---|
| `EMPTY` | m̄ < m_off |
| `CUP_DETECTED` | m̄ ≥ m_on, not yet stable |
| `WEIGHT_VERIFIED` | stable at base; load weight recorded; portion within m_nom ± δ (if the product's m_nom is known) |
| `IN_TRANSIT` | robot left with the cup (`RECORRIDO_MESA_n`) |
| `AT_TABLE` | robot `EN_MESA`; settling, then the delivery weight is recorded |
| `PICKUP_PENDING` | weight dropped below m_off at the table; debounce running |
| `PICKUP_DETECTED` | confirmed: `RETIRADO` sent once (latched for this trip) |
| `CUP_LOST` | the cup disappeared in transit or wasn't there on arrival (incident `Vaso`) |
| `NO_DATA` | no frame for t_stale (link or sensor down): **never** sends `RETIRADO` |
| `SENSOR_FAULT` | implausible values (m < −100 g or m > 1500 g). **Not** −20 g: the real adapter sends one −30 to −50 g frame on every removal |

Transitions (A1–A14). Each one is a numbered branch in the code, like T1–T17:

| # | From | Condition | Action | To |
|---|---|---|---|---|
| A1 | EMPTY | m̄ ≥ m_on | — | CUP_DETECTED |
| A2 | CUP_DETECTED | stable for t_stable **and** robot `ESPERANDO_ORDEN` | record **load weight** (PesoCarga_g); portion check | WEIGHT_VERIFIED |
| A3 | CUP_DETECTED / WEIGHT_VERIFIED | m̄ < m_off | — | EMPTY |
| A4 | WEIGHT_VERIFIED | robot → `RECORRIDO_MESA_n` | remember the trip's `robot_msg_id` | IN_TRANSIT |
| A5 | IN_TRANSIT | m̄ < m_off for t_confirm | incident `CUP_LOST_IN_TRANSIT` (alert; robot keeps going) | CUP_LOST |
| A6 | IN_TRANSIT | load − m̄ > Δm (stable) | warning `SPILL` (flag only) | IN_TRANSIT |
| A7 | IN_TRANSIT | robot → `EN_MESA` | — | AT_TABLE |
| A8 | AT_TABLE | t ≥ t_settle **and** stable **and** m̄ ≥ m_on | record **delivery weight** (PesoEntrega_g) | **armed** (stays AT_TABLE) |
| A9 | AT_TABLE (armed) | m̄ < m_off | start debounce | PICKUP_PENDING |
| A10 | PICKUP_PENDING | any frame ≥ m_on (put back) | — | AT_TABLE |
| A11 | PICKUP_PENDING | **every** frame < m_off for t_confirm, no frame gap > t_gap, **all interlocks hold** (§3) | **SEND_RETIRADO** | PICKUP_DETECTED |
| A12 | AT_TABLE / PICKUP_* | robot leaves `EN_MESA` (timeout, manual `RETIRADO`) | — | EMPTY or CUP_LOST |
| A13 | any | no frame for t_stale | alert | NO_DATA |
| A14 | NO_DATA / SENSOR_FAULT | frames valid again for 3 frames | **re-derive state from weight and robot state; never jump to PICKUP_DETECTED** | (re-derived) |

If the robot is dispatched without a verified cup (operator override), the FSM goes from
`EMPTY` to `CUP_LOST` on arrival. That means no automatic pickup, and the robot returns by timeout or the manual button.

### 2.3 Order lifecycle: completes the timestamps (statuses stay configurable)

Driven by robot events that Phase 4 already stores. Status names come from `order_config.json` and are still not fixed:

| Event | Order fields |
|---|---|
| `EVT LLEGO orden=<id>` | `arrived_at` |
| `OK RETIRADO` (auto or manual) | `delivered_at`, `delivery_weight_g`, cause `pickup:scale` or `pickup:admin` |
| `TRANSICION a=REGRESO_BASE causa=t_entrega` | incident `Vaso` (nobody took it) |
| `TRANSICION a=ESPERANDO_ORDEN causa=en_base` | `returned_at`; incident `Ninguna` if none |
| AdapterFSM A2 | `load_weight_g` |

These are the same rules as `SeguimientoPedidos` and `registro_pruebas.py`, so the dashboard's Pedidos sheet fills automatically.

---

## 3. Safety and debounce

**Rule 0: missing data is never "cup removed".** Only a sequence of real frames below m_off counts.
Silence, a closed port or a parse error leads to `NO_DATA`, and the robot falls back to `t_entrega`.

`SEND_RETIRADO` requires **all** of these (checked in A11 and again just before sending):

1. Adapter state `PICKUP_PENDING` for ≥ **t_confirm**, with **every** frame in that window < m_off (hysteresis: 150 g on, 50 g off).
2. No gap > **t_gap** between frames in the window, and the last frame is newer than t_stale.
3. The cup was **seen at the table**: A8 armed (stable ≥ m_on after t_settle). This blocks a `RETIRADO` caused by braking vibration or by a cup lost on the way.
4. The robot is `EN_MESA` **and** `ClienteRobot.orden == robot_msg_id` of this trip (`RETIRADO` carries no order id, so the platform checks it).
5. ≥ **t_settle** since `EN_MESA` (braking and settling).
6. Not already sent for this `robot_msg_id` (latch). `ClienteRobot` retries with the same id, so the robot never sees it twice.
7. Mode `auto_pickup = on` (see shadow mode).

Initial parameters (`adapter_config.json`, changeable without migration or reflash):

| Parameter | Value | Why |
|---|---|---|
| m_on / m_off | 150 g / 50 g | Paper FR-01/FR-02; empty cup + lid ≈ tens of g, full ≈ 350 g |
| t_settle | 1.0 s | Braking and settling at the table |
| t_stable | 3 frames within ±2 g | Recording PesoCarga/PesoEntrega |
| **t_confirm** | **1.2 s (≥ 2 consecutive frames)** | Rejects a single glitch frame and a lift-and-put-back under 1.2 s |
| t_gap | 1.0 s | A frame should arrive every 0.6 s |
| t_stale | 3.0 s | ≈ 5 missed frames → `NO_DATA` |
| Δm | 5 g | Spill flag (paper) |
| Plausible range | −100 g … 1500 g | Outside → `SENSOR_FAULT`. Single negative undershoot frames (−30…−50 g) are **normal** on removal (log 17 Nov) |

**Expected latency** from lift to robot moving: 0–0.6 s until the first frame below 50 g, + 1.2 s confirm,
+ ~0.1 s (BT + HTTP + TCP/WiFi + 1 FSM cycle) ≈ **1.3–1.9 s**. This also gives the customer's hand time to clear
before the robot moves. If it feels slow, ask the firmware for a frame every 0.3 s (3 samples) before shortening t_confirm.

**Thermal drift (hot cup):** a software tare is taken in `EMPTY` at base (stable 3 frames) before each load. That's the
paper's "tare before each order", done in the backend without a downlink. A slow drift of a few grams can't cross
a 100 g hysteresis band.

**Manual override always stays:** the admin "Retirado" button sends the same `ClienteRobot.retirado()`.

**Shadow mode** (`auto_pickup = shadow`): the FSM runs live, logs `SEND_RETIRADO (shadow)`, and the admin page shows
"would send now", but nothing is sent. Run every real trip in shadow mode until the false-positive count is zero (§7).

---

## 4. Protocol and message formats

### 4.1 Adapter → PC (Bluetooth SPP, 9600 8N1, ASCII lines, `\n`)

| Line | When | Status |
|---|---|---|
| `PESO:352.4` | about every 0.6 s, mean of 6 samples, 1 decimal, grams | **Existing**: the bridge accepts it as-is |
| *(ready message)* | at start-up | Existing: logged, used as a "reset" marker |

No clock on the adapter: the **PC stamps the time on reception** (paper FR-05).
PC → adapter: none required. An optional `TARA` command can come later; the software tare covers it.

### 4.2 Bridge → backend (HTTP, localhost)

`POST /api/scale/readings` (implemented, 5.1)

```json
{ "source": "COM5",
  "readings": [ { "raw": "PESO:349.3", "grams": 349.3, "received_at": "2026-11-17T20:12:11.482+00:00" } ] }
```

- `received_at` is set by the bridge on serial reception (closest to the physical event). The backend adds `ingested_at`.
  Measured bridge-to-DB delay: p95 = 5 ms.
- Lost frames can't be detected from a counter (the firmware has none). They show up as **gaps in `received_at`**:
  > 1 s gap → don't trust the window, > 3 s → `stale`.
- `POST /api/scale/link` `{ "source", "port_open", "detail", "counters" }` when the port opens or closes, and every 5 s as a heartbeat.
- If the backend is unreachable, the bridge keeps reading, writes `scale_raw_<date>.csv` locally, and retries (the data isn't lost).

### 4.3 Backend → robot

`RETIRADO id=<n>` through `ClienteRobot.retirado()`, which already exists. Expected `OK RETIRADO id=<n> estado=REGRESO_BASE`,
then `EVT TRANSICION … a=REGRESO_BASE causa=vaso_retirado`.

### 4.4 Backend → admin page (WebSocket, same envelope as before)

| `type` | `data` | Rate |
|---|---|---|
| `scale.reading` | `{grams, received_at, adapter_state}` | ≤ 2 Hz |
| `adapter.status` | `{state, link, armed, order_id, load_g, delivery_g, mode}` | on change + every 5 s |
| `adapter.transition` | `{from, to, cause, grams, at}` | on change |
| `order.updated` | Order | as today |

### 4.5 Persistence

| Table | Content |
|---|---|
| `scale_readings` (exists) | every frame: `received_at`, `grams`, `raw`, `order_id`. About 6,000 rows/h |
| **`adapter_events`** (NEW, migration 0002) | every AdapterFSM transition: `at`, `from_state`, `to_state`, `cause`, `grams`, `order_id`, `robot_msg_id`, `mode` |
| `order_events` | `pickup:scale` / `pickup:admin` / `pickup:timeout` |

---

## 5. Responsibilities

| Component | Runs | Does | Does NOT |
|---|---|---|---|
| Adapter MCU (Nano + HX711 + HC-05) | on the robot | read HX711 at 10 SPS, calibration factor, average, send `PESO:` lines; optional `N`, `V` | decide anything, know orders or robot state, keep time |
| OAK9 + ESP32 firmware | robot | unchanged | — |
| `main_real.py` / `fsm.py` | PC, native | unchanged; accepts `RETIRADO` in `EN_MESA`; `t_entrega` fallback | read the scale |
| **`scale_bridge.py`** (new) | PC, native (Docker can't open COM ports) | open the COM port, reconnect, parse, stamp UTC, POST; local CSV backup; `--source sim` / `--source replay` | decide anything |
| **Backend** | Docker | AdapterFSM, debounce, interlocks, `RETIRADO` via ClienteRobot, tare, order timestamps and weights, persistence, WebSocket | talk to COM ports |
| Admin page | browser | live weight, adapter state, "would send" in shadow mode, manual Retirado, alerts | — |

---

## 6. Implementation plan (each step testable before the next)

| Step | Work | Done when |
|---|---|---|
| **5.0** | Pair the HC-05 (or ESP32) with Windows and note the **outgoing** COM port. Record 10 min of raw frames with a serial terminal: idle, place, lift, tap the table, hot cup 3 min | Frame period and noise confirmed; raw log saved for replay |
| **5.1** | `scale_bridge.py` (COM / sim / replay sources) + `POST /api/scale/readings` + `scale_readings` + `scale.reading` on the admin page + health `scale` | Live weight visible on `/admin`; unplug BT → "no data" within 3 s |
| **5.2** | `AdapterFSM` (pure) + table-driven unit tests (§7) + replay of the 5.0 log | All scenarios pass; replay gives the expected transitions |
| **5.3** | Migration 0002 `adapter_events`; FSM wired live in **shadow** mode; admin panel | Shadow decisions logged and shown; nothing sent |
| **5.4** | Order lifecycle from robot events (arrived/delivered/returned, weights, incident); manual **Retirado** button | Pedidos columns filled automatically for a manual trip |
| **5.5** | `auto_pickup = on`: A11 → `ClienteRobot.retirado()` with all interlocks | Full loop green against `servidor_simulado.py` + simulated scale |
| **5.6** | Bench: real adapter on the **stopped** robot (paper's next increment) | 30/30 removals detected, 0/30 false on touches, latency p95 < 2 s |
| **5.7** | Real trips in shadow, then on: 10 runs per table | 0 false `RETIRADO`, 0 misses; data in the dashboard |

---

## 7. Simulation and testing

1. **Unit tests of the AdapterFSM** (pure function, synthetic time, like the 27 FSM tests). Scenarios:
   normal pickup · lift-and-put-back < t_confirm · single 0 g glitch frame · braking vibration at arrival ·
   BT drop **during** PICKUP_PENDING (must NOT send) · stale link at the table · cup lost in transit ·
   dispatched without a cup · robot timeout before pickup · `RETIRADO` sent exactly once ·
   robot not `EN_MESA` / different order (must NOT send) · spill Δm · slow thermal drift · implausible values.
2. **Replay:** the bridge's `--source replay file.csv` feeds real bench logs (5.0) at real or accelerated speed. Every field incident becomes a new replay test.
3. **Simulated adapter:** `scale_bridge.py --source sim` takes keyboard commands like `servidor_simulado.py`'s fault injection:
   `poner 352`, `quitar`, `tocar` (lift and return 0.5 s), `vibrar`, `corte 5`, `derramar 8`, `caliente`. No com0com needed.
4. **Full loop without hardware:** `servidor_simulado.py --entrega 180` + `scale_bridge.py --source sim` + platform:
   order → dispatch → `EN_MESA` → `quitar` → `RETIRADO` → `REGRESO_BASE`. Use `--entrega 180` so the timeout doesn't hide a miss.
5. **Bench with real hardware, robot stopped** (5.6): measure latency from the bridge stamp to `OK RETIRADO`.
6. **Field runs** (5.7): shadow first, then on.

**Acceptance criteria:** 100 % of removals detected · **0 false `RETIRADO`** (touches, vibration, transit, link drops) ·
lift-to-`OK RETIRADO` latency p95 < 2 s · with the bridge or backend stopped, the robot still returns by `t_entrega`.

---

## 8. Decisions

Resolved 17 Nov: the adapter stays **Nano + HC-05** with the deployed firmware (`PESO:<g>` only); no frame
counter or voltage; timestamps by the PC; decisions in the backend; robot FSM unchanged.

Still open:
1. **Cup lost in transit:** alert only (recommended) or also `PAUSA`?
2. **Auto-dispatch on placement:** recommended **no**. Keep the barista's Dispatch button, with a weight interlock later.
3. Product m_nom values (cup + lid tare and portion per C1/C2/C3) for the portion check.
4. Confirm `t_entrega = 180 s` in operation (`main_real.py --entrega 180`).

Closes `09_pendientes`: "Quién manda RETIRADO" → **cell (automatic) + app button (manual override)**.
