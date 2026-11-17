# RoboCoffee Platform

Order platform for the RoboCoffee OAK9 delivery robot. Architecture and phase plan: [`docs/architecture.md`](docs/architecture.md).

```
robocoffee-platform/
├── docker-compose.yml   # db + backend + frontend
├── .env.example
├── backend/             # FastAPI           (Docker)
├── frontend/            # React + TS + Vite (Docker)
├── robot/               # existing robot subsystem, intact (native Windows)
├── scale_bridge/        # Bluetooth load cell → backend (native Windows, later phase)
└── docs/
```

## Run (Windows, Docker Desktop)

```bat
copy .env.example .env
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:5173 | Customer ordering page |
| http://localhost:5173/status | Platform status + recent orders |
| http://localhost:8000/api/health | Backend health JSON (includes the applied schema revision) |
| http://localhost:8000/api/orders | Orders JSON (newest first, `?status=` `&limit=`) |
| http://localhost:8000/docs | Interactive API docs |

Stop: `Ctrl+C`, then `docker compose down`. Add `-v` to also delete the database volume.

Database migrations run automatically on backend start. See [`docs/migrations.md`](docs/migrations.md).
Products, tables and the provisional order statuses are in `backend/app/order_config.json`.

## Tests

```bat
docker compose exec backend pytest -q
```

Tests use a separate `robocoffee_test` database, rebuilt from the migrations on every run.
Your development data is never touched.
