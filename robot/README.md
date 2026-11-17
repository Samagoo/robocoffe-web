# robot/ — existing robot subsystem (external, kept intact)

Copy the **entire** existing robot codebase into this folder **unchanged**:
`main_real.py`, `servidor_simulado.py`, the `robocoffe_fsm/` package, `cliente/`, Webots files, tests, docs.

The platform **does not modify or import** anything in this folder. The only contract between the two is
the existing line protocol on **TCP port 9000** (`docs/02_protocolo.md` of the robot code):

| Platform → robot | Robot → platform |
|---|---|
| `ORDEN id=<n> destino=MESA1..3` | `OK <cmd> id=<n> k=v …` |
| `RETIRADO`, `CANCELAR`, `PAUSA`, `REANUDAR`, `RESET` | `ERROR <cmd> id=<n> <MOTIVO>` |
| `ESTADO`, `PING` (queries) | `EVT TRANSICION/LLEGO/TRAMO/ERROR/LATIDO …` |

## Running it (natively on Windows, not in Docker)

```bat
:: Real OAK9 (WiFi). Robot IP is always passed as an argument.
python main_real.py --host 192.168.1.173 --entrega 180

:: Without the robot: use the existing simulator, which also listens on :9000
python servidor_simulado.py
```

The backend container reaches it at `host.docker.internal:9000` (set in `.env`).
