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
| http://localhost:5173 | Web app (status page in Phase 1) |
| http://localhost:8000/api/health | Backend health JSON |
| http://localhost:8000/docs | Interactive API docs |

Stop: `Ctrl+C`, then `docker compose down`. Add `-v` to also delete the database volume.
