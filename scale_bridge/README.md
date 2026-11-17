# scale_bridge/ — load cell over Bluetooth (reserved; implemented in a later phase)

The coffee adapter (Arduino Nano + HX711) sends weight over Bluetooth, which Windows exposes
as a COM port (`SCALE_COM_PORT` in `.env`).

## Why a separate native process

Docker Desktop on Windows **cannot open COM ports**, so the backend container can't read the scale
directly. A small Python process runs natively on Windows, reads the COM port and forwards each
reading to the backend:

```
Arduino/HX711 ─BT─► COMx ─► scale_bridge (native, pyserial) ─HTTP POST─► backend /api/scale/readings
                                                                             │
                                             stores in scale_readings ◄──────┤
                                             if cup removed while EN_MESA ───┘──► "RETIRADO id=…" to main_real :9000
```

The last step reuses what already exists: the robot FSM already accepts `RETIRADO` over TCP
to end the wait at the table. No change to the robot code is needed.

## Reserved interface (backend)

- `POST /api/scale/readings`: `{ "grams": float, "device_time_ms": int | null, "raw": str }`.
  The backend adds the UTC receive timestamp.
- Table `scale_readings`: `id, received_at (timestamptz), grams, raw, order_id (nullable)`.

## Open questions before implementing

1. What does the Arduino send per line (format, units, rate)?
2. Is the 50 g "cup removed" threshold done on the Arduino or on the platform?
3. Does anything else currently open this COM port? Only one process can hold it at a time.
