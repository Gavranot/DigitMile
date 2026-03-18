# Backend Operations and Configuration

Last updated: 2026-03-18

## Why this subsystem exists

This document covers how the Django backend is configured, started, observed, and safely changed in development and production-like environments.

## Runtime topology

From `docker-compose.yml` and `docker-compose.localhost.yml`:

- `db` — PostgreSQL 16
- `pgbouncer` — PgBouncer connection pooler (sits between Django and PostgreSQL)
- `backend` — Django + Gunicorn (5 workers)
- `frontend` — Unity/nginx frontend
- optional `nginx-proxy` — local HTTPS reverse proxy

Traffic model:

- users reach nginx/frontend
- backend is mounted under `/panel/`
- Django admin and API are both behind that mount point
- Django connects to `pgbouncer`, not directly to `db`; PgBouncer forwards to `db`

## Application bootstrap

### Django settings highlights

Configured in `DigitMilePanel/digitmile/settings.py`.

- database engine: PostgreSQL
- static files: WhiteNoise with compressed manifest storage
- installed apps: `digitmileapi`, Django admin/auth apps, `corsheaders`, `rest_framework`, `captcha`
- middleware includes custom `HealthCheckMiddleware`
- supported languages: English, Macedonian, Albanian
- login URLs:
  - `LOGIN_URL = /panel/`
  - `LOGIN_REDIRECT_URL = /panel/`
  - `LOGOUT_REDIRECT_URL = /panel/`

### Compose startup sequence

The backend container command runs, in order:

1. migrations — run with `DB_HOST=db` (bypasses PgBouncer; see [PgBouncer and Django migrations](#pgbouncer-and-django-migrations))
2. static collection
3. custom superuser creation command
4. gunicorn with 5 workers

### Docker images

`DigitMilePanel/Dockerfile` and `DigitMilePanel/Dockerfile.compose` both:

- use Python 3.12 slim
- install `libpq-dev`, `gcc`, `gettext`
- install Python requirements from `requirements.txt`

## Configuration matrix

### Core Django and database variables

| Variable | Used in code | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | yes | Django secret key |
| `DEBUG` | yes | toggles Django debug mode |
| `DB_NAME` | yes | PostgreSQL database name |
| `DB_USER` | yes | PostgreSQL username |
| `DB_PASS` | yes | PostgreSQL password |
| `DB_HOST` | yes | Database host. Must be `pgbouncer` in all environments (dev and prod). Set to `db` only when running migrations directly — see [PgBouncer and Django migrations](#pgbouncer-and-django-migrations). |
| `DB_PORT` | yes | PostgreSQL port; parsed carefully, defaults to 5432 when unset |
| `SERVER_IP` | yes | appended to `ALLOWED_HOSTS` when present |
| `ALLOWED_HOSTS` | yes | comma-separated host allowlist |

### Email variables

| Variable | Used in code | Purpose |
| --- | --- | --- |
| `EMAIL_BACKEND` | yes | console vs SMTP backend |
| `EMAIL_HOST` | yes | SMTP host |
| `EMAIL_PORT` | yes | SMTP port |
| `EMAIL_USE_TLS` | yes | TLS toggle |
| `EMAIL_HOST_USER` | yes | SMTP username |
| `EMAIL_HOST_PASSWORD` | yes | SMTP password |
| `DEFAULT_FROM_EMAIL` | yes | sender address |
| `SITE_URL` | yes | links included in teacher emails |

### Product-specific variables

| Variable | Used in code | Purpose |
| --- | --- | --- |
| `GOOGLE_MAPS_API_KEY` | yes | map picker on school registration page |

### Superuser bootstrap variables

Used by `DigitMilePanel/digitmileapi/management/commands/create_superuser.py`:

- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_EMAIL`
- `DJANGO_SUPERUSER_PASSWORD`

If the password variable is absent, the command logs a warning and skips user creation.

## Data stores and file-backed inputs

### Primary database

- PostgreSQL is the intended runtime database.
- A `db.sqlite3` file exists in the repository, but runtime settings point to PostgreSQL.

### File-backed analytics inputs

- level deck JSON files in `DigitMilePanel/digitmileapi/templates/assets/`
- locale files in `DigitMilePanel/locale/`

### Static files

- collected into `DigitMilePanel/staticfiles/`
- served by WhiteNoise

## Security-relevant behavior

### CSRF and sessions

- Unity is expected to fetch a CSRF token and send it in `X-CSRFToken`.
- Only the token-fetch endpoint bypasses CSRF enforcement.

### CORS

- `CORS_ALLOW_ALL_ORIGINS = True`
- this is intentionally permissive and should be treated as a conscious trust decision

### Host handling and health checks

- `ALLOWED_HOSTS` is environment-driven
- `HealthCheckMiddleware` returns `{"status": "healthy"}` for any path containing `health`
- this happens before normal processing and is intended to keep health probes simple

### Soft rejection model

- rejecting a school or teacher disables access without deleting data
- this is good for auditability but means rejected records stay in the database indefinitely

### Teacher auth posture

- teacher users are staff users and can enter Django admin
- object scoping is implemented in admin/view code, not via separate admin sites or object-permission libraries

## Observability and troubleshooting

### Logging

Logging is configured to stdout only.

- root logger -> console
- `django` logger -> console
- `email` logger -> console

Code quality note:

- some code paths still use `print()` and raw traceback printing, especially older API endpoints
- newer ingestion and email paths use structured `logger.info/warning/error/exception`

### Caching

- there is no explicit `CACHES` setting in `settings.py`
- teacher visualization payloads use `django.core.cache.cache`
- effective backend therefore depends on Django defaults unless overridden elsewhere

### Useful operational commands

From `AGENTS.md`:

- start stack: `docker-compose up -d`
- start with localhost HTTPS: `docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d`
- backend logs: `docker-compose logs -f backend`
- run migrations: see [PgBouncer and Django migrations](#pgbouncer-and-django-migrations) — do not use the plain `migrate` command
- Django shell: `docker-compose exec backend python manage.py shell`
- create/update teachers group: `python manage.py setup_teachers_group`
- clear school/game data: `python manage.py clear_school_data --yes`

## Background/bootstrap commands in the app

### `setup_teachers_group`

- re-runs teacher group permission provisioning

### `create_superuser`

- idempotently creates a superuser from env vars

### `clear_school_data`

- destructive command that deletes schools, teachers, classrooms, students, runs, triggers, and teacher-linked users
- intentionally keeps the confirmation prompt unless `--yes` is provided

### `seed_database`

- creates demo schools, teachers, classrooms, students, runs, triggers, and optional legacy stats
- useful for dashboard and analytics testing

## PgBouncer and Django migrations

### What PgBouncer does

PgBouncer is a connection pooler that sits between Django and PostgreSQL. Without it, every HTTP request that Django handles opens a new TCP connection to PostgreSQL, authenticates, runs its queries, and closes the connection. At load this is wasteful: opening a connection costs ~2–5 ms and forces PostgreSQL to spawn a new backend process (~5 MB RAM each) for every request.

PgBouncer maintains a warm pool of already-open connections to PostgreSQL. Django "connects" to PgBouncer (which is instantaneous — same Docker network, no auth round-trip), borrows a real connection from the pool, runs its queries, and returns the connection when the transaction commits. PostgreSQL never sees the per-request connect/disconnect churn.

### Transaction pooling mode

PgBouncer is configured in **transaction pooling mode** (`PGBOUNCER_POOL_MODE=transaction`). In this mode, a real PostgreSQL connection is held only for the duration of a single transaction — it is released back to the pool the moment Django calls `COMMIT` or `ROLLBACK`. This means 5 Gunicorn workers can share as few as 5–10 real PostgreSQL connections instead of holding 5 open permanently.

Two Django settings are required for this to work correctly:

```python
# settings.py — DATABASES["default"]
"CONN_MAX_AGE": 0,
"DISABLE_SERVER_SIDE_CURSORS": True,
```

- `CONN_MAX_AGE=0` — Django must not hold a persistent connection across requests. If it did, PgBouncer could not reclaim the connection between transactions, defeating the pool. PgBouncer owns the pool; Django treats each request as stateless.
- `DISABLE_SERVER_SIDE_CURSORS=True` — PostgreSQL prepared statements and server-side cursors are tied to a specific backend connection by session ID. In transaction mode, the same Django "connection" is routed to different real PostgreSQL connections on each transaction. Prepared statements therefore break silently. This setting tells Django's ORM to avoid them entirely.

### Why migrations cannot run through PgBouncer

Django's migration system acquires a **PostgreSQL advisory lock** at the start of every `migrate` run:

```sql
SELECT pg_try_advisory_lock(hash_of_app_label_and_migration_name);
```

Advisory locks in PostgreSQL are **session-scoped** — they are held for the lifetime of a database session, not a transaction. In transaction pooling mode, a session does not correspond to a single real PostgreSQL connection. When the migration's first transaction commits, PgBouncer releases the underlying connection back to the pool and may route the next transaction to a completely different PostgreSQL backend. The advisory lock, held by the original session, is lost. Django then fails to detect that its own lock has disappeared and either errors out or, worse, allows two concurrent `migrate` processes to run simultaneously.

### What to do instead

**Always run migrations with `DB_HOST=db`**, which bypasses PgBouncer and connects Django directly to PostgreSQL for that process only.

**In development (docker-compose):**

The compose startup command already does this:

```yaml
command: >
  sh -c "DB_HOST=db python manage.py migrate && ..."
```

`DB_HOST=db` is set only for the `migrate` subprocess. Django reads `os.getenv("DB_HOST")` at startup, so this override is scoped to that single process. Gunicorn, started later in the same `sh -c` chain without the override, picks up `DB_HOST=pgbouncer` from the container's `.env` and connects through the pool.

**In production (manual or CI migrations):**

```bash
# via docker exec on the running backend container
docker exec -e DB_HOST=db digitmile-backend python manage.py migrate

# or via docker-compose exec
DB_HOST=db docker-compose exec backend python manage.py migrate
```

Do not run `docker-compose exec backend python manage.py migrate` without the `DB_HOST=db` override. The container's `.env` sets `DB_HOST=pgbouncer`, so a plain `migrate` command will route through PgBouncer and fail on the advisory lock.

### Summary

| Operation | Connect through | Why |
| --- | --- | --- |
| Normal request handling (Gunicorn) | `pgbouncer` | Pool reduces per-request connection overhead |
| `python manage.py migrate` | `db` (direct) | Advisory locks require a stable session |
| `python manage.py shell` | `pgbouncer` | Fine — no advisory locks in an interactive shell |
| `python manage.py` any other command | `pgbouncer` | Fine for all other management commands |

## Performance characteristics and hotspots

### Relatively efficient parts

- run ingestion uses `transaction.atomic()` plus `bulk_create()` for turns and triggers
- `Run` and `TurnEvent` have indexes aligned with common analytics access patterns

### Potential hotspots

- dashboard page computes student summaries in Python per student, which can get expensive for large classes
- several analytics helpers iterate through raw turn rows in Python rather than relying fully on SQL aggregation
- deck/share and conditional analytics parse JSON/card data repeatedly
- replay loads all turns for a run at once into the template

## Safe change guidance

### If changing model fields

- inspect both ingestion endpoints
- inspect `analytics.py`
- inspect admin read-only field lists and filters
- inspect dashboard JSON serialization in `teacher_statistics_dashboard`

### If changing auth or teacher access

- inspect `apps.py` group permissions
- inspect `IsTeacher`
- inspect admin `get_queryset()` and permission overrides
- inspect status transition side effects in `models.py`

### If changing Unity payload shape

- update serializer(s)
- update normalization helpers in `views.py`
- update replay parsing logic in `teacher_run_replay.html`
- verify card analytics still parse the stored payload correctly

## Evidence-backed technical debt

- legacy and current gameplay data paths coexist and are only partially harmonized
- `insertRunData/` and `runs/ingest/` are not semantically identical despite similar purpose
- some public approval/rejection actions are GET routes
- duplicate-handling logic is inconsistent between forms and database constraints
- no automated tests currently exercise this behavior; `DigitMilePanel/digitmileapi/tests.py` is effectively empty

## Open questions / uncertainty notes

- Because no test suite covers the current backend behavior, code inspection is the main source of truth for all docs here.
- Production cache backend, email backend, and host values may vary by deploy environment beyond what is represented in repository defaults.
