# Getting Started

A cold-start walk-through for running DigitMile locally. This is the fastest path to a working dev stack; see `docs/guides/deployment.md` for production bring-up.

## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`).
- `git`.
- ~2 GB of free disk and ~2 GB of free RAM for the container stack.
- Python 3.12 is used inside the backend container; you do **not** need a local Python install.

## 1. Clone

```bash
git clone <repo-url> DigitMile
cd DigitMile
```

## 2. Create `.env`

The root `.env` file is read by `docker-compose.yml` and by the backend container. Copy one of the templates:

```bash
cp .env.example .env      # or .env.docker for the docker-compose defaults
```

Edit `.env` and set at minimum:

- `DB_NAME`, `DB_USER`, `DB_PASS` — Postgres creds (any values; the container creates the DB).
- `DB_HOST=pgbouncer` and `DB_PORT=5432` — route traffic through PgBouncer by default.
- `DJANGO_SECRET_KEY` — any long random string for dev.
- `DEBUG=True` for local development.

See `docs/reference/configuration.md` for the full list of variables.

There are also two app-local env files you can ignore for a fresh checkout: `DigitMilePanel/.env` is a legacy per-app env used by some tooling; the container reads the root `.env` via `env_file:` in `docker-compose.yml`.

## 3. Start the stack

Fastest — plain HTTP, no reverse proxy:

```bash
docker compose up -d
```

This brings up six services:

| Service | Port exposed | Role |
|---------|--------------|------|
| `db` | 5432 | PostgreSQL 16 |
| `redis` | — | Dashboard cache + ingest write buffer |
| `pgbouncer` | — | Connection pooler (transaction mode) |
| `backend` | 8000 | Django (Gunicorn, 5 workers); runs migrate + collectstatic + create_superuser on boot |
| `flusher` | — | Reads from the Redis ingest buffer and bulk-inserts into Postgres |
| `frontend` | 80 | nginx serving the Unity WebGL build |

Alternative modes:

- Local HTTPS with a self-signed cert: `docker compose -f docker-compose.yml -f docker-compose.localhost.yml up -d` (see `docs/guides/ssl.md`).
- Production with Let's Encrypt: use `docker-compose.prod.yml` — see `docs/guides/deployment.md`.

## 4. Create a superuser

The backend container runs `python manage.py create_superuser` on boot. That command no-ops if `DJANGO_SUPERUSER_USERNAME` / `_PASSWORD` / `_EMAIL` aren't set in `.env`. If you didn't set them, create one interactively:

```bash
docker compose exec backend python manage.py createsuperuser
```

## 5. Seed some data (optional)

```bash
docker compose exec backend python manage.py seed_database --preset medium
```

Presets are `low` / `medium` / `high`. This creates schools, teachers, classrooms, students, runs, and weekly rollups. See `docs/reference/management-commands.md` for the other flags.

## 6. Log in

| URL | What you get |
|-----|--------------|
| http://localhost/ | The Unity WebGL game |
| http://localhost:8000/panel/ | The teacher/admin site (the game container proxies to this too when the nginx-proxy is running) |
| http://localhost:8000/panel/admin/ | Django admin |
| http://localhost:8000/panel/health/ | Health check — returns `{"status": "healthy"}` |

## 7. Run the tests (optional)

```bash
docker compose exec backend python manage.py test digitmileapi
```

See `docs/guides/testing.md` for scope and how to target specific test classes.

## What's next

- **Make backend changes:** code is bind-mounted from `DigitMilePanel/` into the container, so edits hot-reload on Gunicorn restart (`docker compose restart backend`).
- **Run a benchmark:** `python benchmarks/run_scenario.py benchmarks/scenarios/realistic_school_day.json` — see `docs/guides/load-testing.md`.
- **Wipe and restart:** `docker compose down -v` drops all volumes (including the Postgres data volume).

## Troubleshooting

- **`backend` fails to start** — check `docker compose logs backend`. The boot command runs `DB_HOST=db migrate` explicitly (bypassing PgBouncer, which deadlocks on Django's advisory-lock during migrations). If you overrode `DB_HOST` incorrectly in `.env`, this is usually the symptom.
- **Ingest endpoint returns 202 but nothing shows up in DB** — the `flusher` service must be running. `docker compose ps flusher` should show it up; `docker compose logs flusher` will show batch-flush logs.
- **Dashboard is empty after seeding** — dashboard reads come from rollup tables only (never from hot `Run` data). `seed_database` already runs rollups; if you compacted a week manually and still see nothing, `docker compose exec backend python manage.py rebuild_weekly_rollups <YYYY-MM-DD>` will rebuild the rollup cache.
