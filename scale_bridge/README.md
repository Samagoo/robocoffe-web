# scale_bridge/: adapter weight → backend (Phase 5.1)

The adapter (Nano + HX711 + HC-05, firmware already deployed and **not changed**) sends only lines like
`PESO:349.3`. It knows nothing about the robot, orders or time. `scale_bridge.py` runs **natively on
Windows** (Docker can't open COM ports) and only:

1. reads `PESO:<g>` lines from the HC-05's COM port;
2. stamps each one with **this PC's UTC time on reception**;
3. writes every line to a local CSV (`scale_logs/scale_raw_<date>.csv`): a raw backup, reusable for replay;
4. forwards the readings to the backend (`POST /api/scale/readings`). If the backend is down it queues them
   (up to about 3 h) and sends them later, in order.

It makes **no decisions**. Cup detection and `RETIRADO` belong to the backend (Phase 5.2+).

```
Nano+HX711 ──HC-05~~BT~~► COM5 ──► scale_bridge.py ──HTTP──► backend ──► scale_readings ──► /admin (live)
```

## Setup (once)

1. Pair the HC-05 in Windows Bluetooth settings (PIN is usually `1234` or `0000`).
2. *More Bluetooth options* → *COM Ports*: use the port marked **Outgoing** (e.g. `COM5`).
3. `py -m pip install -r scale_bridge/requirements.txt`
4. `py scale_bridge/scale_bridge.py --list` shows the ports.

Only one program can open a COM port. Close the Arduino Serial Monitor or PuTTY first.

## Run

```bat
:: Real adapter
py scale_bridge\scale_bridge.py --port COM5

:: Without hardware: replay the real bench log (17 Nov) at the adapter's pace
py scale_bridge\scale_bridge.py --replay scale_bridge\samples\bench_2026-11-17.txt

:: Without hardware: simulated adapter (type commands + Enter)
py scale_bridge\scale_bridge.py --sim
::   poner 349.3   quitar   tocar   glitch   corte 5   estado
```

Options: `--backend http://localhost:8000` · `--baud 9600` · `--period 0.6` (replay/sim) · `--loop` · `--log-dir scale_logs`.

The simulator reproduces what the real log shows: 1–2 intermediate frames when a cup is placed, and one
**negative undershoot frame (−30 to −50 g)** right after a removal.

Each run's `source` is stored with every reading (`COM5`, `sim`, `replay:<file>`), so test data never
mixes with real data in analysis.

## Status seen by the platform (`GET /api/scale`, admin page)

| `link` | Meaning |
|---|---|
| `live` | readings arriving |
| `stale` | port open but no reading for 3 s (adapter off, out of range, battery). **Silence is never treated as 0 g** |
| `port_closed` | bridge running, COM port not open (it retries every 3 s) |
| `offline` | bridge not running (no heartbeat for 15 s) |

## Tests

```bat
py -m pytest scale_bridge
```

These are parser, ordering and retry tests with the backend down, plus the bounded queue, the simulator artifacts, and a
fake serial port (pseudo-terminal, skipped on Windows).
