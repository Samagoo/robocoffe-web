# Database migration strategy (Alembic)

## How it works

- `app/models.py` is the source of truth for the schema.
- Every schema change is an Alembic revision in `backend/migrations/versions/`, committed to git.
- **Migrations run automatically** when the backend container starts (`alembic upgrade head`).
  If one fails, the backend does not start. Check `docker compose logs backend`.
- `/api/health` reports `database.schema_revision`, so you can see which revision is applied.
- **Business vocabulary is NOT in the schema.** Statuses, products and tables come from
  `app/order_config.json`, and `orders.status` is plain text. Renaming a status or re-measuring a
  distance only needs a backend restart, not a migration.

## Rules

1. **Never edit a migration that is already on `main`.** Create a new one instead.
2. One revision per logical change, with a short descriptive message.
3. Autogenerate a draft, then **read it**. Autogenerate misses renames: it shows them as a drop plus an add, which loses data.
4. Every `upgrade()` has a working `downgrade()`.
5. Before committing, `alembic check` must say *No new upgrade operations detected*.

## Commands (from the repo root, with the stack running)

```bat
:: Current revision / history
docker compose exec backend alembic current
docker compose exec backend alembic history

:: After changing app/models.py: draft a new revision (file appears in backend/migrations/versions)
docker compose exec backend alembic revision --autogenerate -m "add xyz to orders"

:: Apply / roll back one step
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1

:: Models and migrations in sync?
docker compose exec backend alembic check

:: Start over with an empty database (DELETES ALL DATA)
docker compose down -v
docker compose up --build
```

## Revisions

| Rev | Content |
|---|---|
| 0001 | `orders`, `order_events`, `robot_events`, `scale_readings` |
