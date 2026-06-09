# Backend Operations and Configuration

Last updated: 2026-05-29

## Why this document exists

How the Django backend is configured, started, observed, and safely changed in development and production. For first-time setup, see `docs/getting-started.md`. For production bring-up, see `docs/guides/deployment.md`. For the weekly compaction lifecycle, see `docs/guides/rollup-runbook.md`.

## Runtime topology

From `docker-compose.yml` (always-on) and `docker-compose.prod.yml` (prod overlay):

| Service | Always-on | Role |
|---|---|---|
| `db` | yes | PostgreSQL 16 |
| `redis` | yes | Ingest write buffer + django-redis dashboard cache |
| `backend` | yes | Django + Gunicorn (5 workers); django-ninja ingest, teacher dashboard, admin |
| `flusher` | yes | `python manage.py flush_ingest_buffer` — drains Redis into Postgres |
| `frontend` | yes | Static nginx serving the Unity WebGL build |
| `nginx-proxy` | prod | TLS termination + reverse proxy (auto-reloads every 6 h) |
| `certbot` | prod | Let's Encrypt renewal loop (every 12 h) |
| `compactor` | prod | Cron container; fires weekly compaction on Friday 20:00 EET |

Traffic flow:

- Users reach the `frontend` (Unity) or `nginx-proxy` (everything else, prod).
- The backend is mounted under `/panel/`. Admin, API, and dashboard all live there.
- Django connects directly to `db` with `CONN_MAX_AGE=60` (PgBouncer was removed from prod — see [PgBouncer history](#pgbouncer-history)).
- Unity ingest goes `Unity → backend → Redis LPUSH → 202` synchronously; persistence happens out-of-band in `flusher`.

## Application bootstrap

### Django settings highlights

Configured in `DigitMilePanel/digitmile/settings.py`:

- Database engine: PostgreSQL (direct, `CONN_MAX_AGE=60`)
- Cache: django-redis (`django_redis.cache.RedisCache`), 7-day TTL for dashboard sections
- Static files: WhiteNoise with compressed manifest storage
- Installed apps: `digitmileapi`, Django admin/auth, `corsheaders`, `rest_framework`, `ninja`, `captcha`
- Middleware includes a custom `HealthCheckMiddleware`
- Supported languages: English, Macedonian, Albanian
- `APPEND_SLASH = False` — callers must hit exact paths
- Login URLs all default to `/panel/`

### Compose startup sequence

The backend container command runs, in order:

1. `python manage.py migrate`
2. `python manage.py collectstatic --noinput`
3. `python manage.py create_superuser`
4. `gunicorn digitmile.wsgi:application --bind 0.0.0.0:8000 --workers 5`

Migrations run normally — Postgres is directly addressable as `db`, no special pooler routing is required.

The `flusher` container's only command is `python manage.py flush_ingest_buffer` with `restart: always`.

The `compactor` container (prod only) is a tiny cron loop that POSTs `/panel/api/internal/compaction/run-weekly/` on its schedule.

### Docker images

`DigitMilePanel/Dockerfile` (CI) and `DigitMilePanel/Dockerfile.compose` (dev) both use Python 3.12 slim and install `libpq-dev`, `gcc`, `gettext`, and `requirements.txt`. The `compactor/Dockerfile` is a separate small image (no Django runtime).

## Configuration matrix

Full env-var reference is in `docs/reference/configuration.md`. Operational highlights:

| Variable | Purpose |
|---|---|
| `DB_HOST` | Always `db` in the current stack. (Historical: `pgbouncer` before pooler removal.) |
| `DB_CONN_MAX_AGE` | Persistent connections; defaults to `60`. |
| `REDIS_URL` | Shared between django-redis cache and the ingest buffer. `redis://redis:6379/1` in compose. |
| `INGEST_BUFFER_BATCH_SIZE` | Default `50`. Max items the flusher pops per iteration. |
| `INGEST_BUFFER_SLEEP_MS` | Default `100`. Idle backoff between drained batches. |
| `INTERNAL_API_TOKEN` | Shared between backend and compactor for the internal compaction trigger. |
| `DJANGO_CACHE_BACKEND` | Default empty = real Redis cache. Set to `dummy` only via benchmark overlay. |
| `DJANGO_SUPERUSER_USERNAME` / `_PASSWORD` / `_EMAIL` | Read by `create_superuser` on boot. Skipped (with a warning) if password is unset. |

## Data stores

- **PostgreSQL** — primary store. A `db.sqlite3` file exists in the repo but runtime settings always point at Postgres.
- **Redis** — ingest buffer (`ingest_buffer` list) + dashboard cache (`teacher_dashboard:*` keys). AOF on with `appendfsync everysec` (bounds loss to ~1 s).
- **Replay archives** — gzipped JSONL files under `REPLAY_ARCHIVE_ROOT` (`/var/lib/digitmile/replay-archives`, bind-mounted volume). One archive per compacted `(teacher, week)`.

## Security-relevant behavior

- **CSRF** — Unity fetches the token from `/panel/api/fetchCSRFToken/` once and sends it in `X-CSRFToken`. Only the token-fetch endpoint bypasses CSRF.
- **CORS** — `CORS_ALLOW_ALL_ORIGINS = True`. Intentional for Unity WebGL builds that may be hosted across origins.
- **Internal endpoints** — `/panel/api/internal/compaction/...` requires the `INTERNAL_API_TOKEN` shared header. Used by the compactor cron container only.
- **Health checks** — `HealthCheckMiddleware` always-200 for paths containing `health`. Use for liveness, not readiness.
- **Soft rejection** — rejecting a school/teacher disables access; data is not deleted (audit trail). Rejected rows stay in the database indefinitely.
- **Teacher auth posture** — teacher users are staff users and can enter Django admin. Scoping is implemented per-view, not via per-object permission libraries.

## Observability and troubleshooting

### Logging

stdout per container. Consume via `docker compose logs -f <service>`.

- Newer ingest, flusher, and compaction paths use structured `logger.info` / `.warning` / `.exception`.
- Older registration/admin paths still emit some `print()` and raw traceback output.

### Key signals to watch

- **`LLEN ingest_buffer`** — should stay near 0 in steady state. Sustained growth means the flusher is behind or down.
  ```bash
  docker compose exec redis redis-cli -n 1 LLEN ingest_buffer
  ```
- **Flusher batch logs** — `docker compose logs -f flusher` shows each drained batch.
- **`WeeklyCompactionRun` rows** — terminal `status` field tells you whether the last Friday's compaction succeeded.
  ```bash
  docker compose exec backend python manage.py shell -c "from digitmileapi.models import WeeklyCompactionRun; print(WeeklyCompactionRun.objects.order_by('-created_at').values('week_start','status')[:5])"
  ```
- **Backend `/panel/health/`** — always-200 even when DB is unhealthy; use it for liveness, not readiness.

### Useful operational commands

- Start stack: `docker compose up -d`
- Start with localhost HTTPS: `docker compose -f docker-compose.yml -f docker-compose.localhost.yml up -d`
- Start in production mode: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
- Tail backend logs: `docker compose logs -f backend`
- Tail flusher logs: `docker compose logs -f flusher`
- Run migrations: `docker compose exec backend python manage.py migrate` (no pooler bypass needed)
- Django shell: `docker compose exec backend python manage.py shell`
- Update teacher group perms: `docker compose exec backend python manage.py setup_teachers_group`
- Wipe school/game data: `docker compose exec backend python manage.py clear_school_data --yes`
- Seed demo data: `docker compose exec backend python manage.py seed_database --preset medium`
- Manually compact a week: see `docs/guides/rollup-runbook.md`.

## Background and bootstrap commands

| Command | Purpose |
|---|---|
| `flush_ingest_buffer` | Long-running flusher. Started automatically by the `flusher` container; should not be run by hand on a live system (it would compete with the container's instance). |
| `compact_weekly_runs` | Per-(teacher, week) compaction worker. Normally fired by the compactor → internal HTTP trigger; can be invoked manually for backfill. |
| `rebuild_weekly_rollups <YYYY-MM-DD>` | Idempotent rebuild of all rollup tables for a given week start. Use after manual changes or to recover from a divergence. |
| `verify_weekly_rollups` | Compares rollup tables against raw rows for a week. Used by compaction before it deletes raw rows. |
| `archive_week_replays` | Writes the `ReplayArchive` rows + gzipped JSONL files. Embedded in `compact_weekly_runs`. |
| `verify_replay_archives` | Spot-check that archives decode to the expected row counts. |
| `setup_teachers_group` | Re-runs teacher group permission provisioning. Safe to call any time. |
| `create_superuser` | Idempotent superuser bootstrap from `DJANGO_SUPERUSER_*` env vars. Runs on every backend boot. |
| `clear_school_data` | Destructive; requires `--yes`. Drops schools, teachers, classrooms, students, runs, triggers, and teacher-linked users. |
| `seed_database` | Demo data: schools, teachers, classrooms, students, runs, triggers, rollups. `--preset low/medium/high`. |
| `prepare_benchmark_dataset` | Used by the benchmark harness, not in production. Builds a deterministic fixture sized to the requested adoption tier. |

Full command catalogue: `docs/reference/management-commands.md`.

## PgBouncer history

PgBouncer used to sit between Django and PostgreSQL in transaction-pooling mode (`CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True`, migrations bypassed it via `DB_HOST=db`). Benchmarks on the production-target VPS showed that once the Redis write buffer (optimization F) was in place, the HTTP ingest path stopped touching PostgreSQL synchronously — and PgBouncer's per-request handshake cost (forced by `CONN_MAX_AGE=0`) started exceeding the savings from pooling. Removing PgBouncer cut average ingest latency from 412 ms to 11 ms on the same hardware.

Production now connects Django directly to `db` with `CONN_MAX_AGE=60`. Server-side cursors are re-enabled. With 5 Gunicorn workers + 1 flusher ≈ 6–7 persistent connections, Postgres's default `max_connections=100` leaves a 14× margin.

The historical pieces are preserved:

- `benchmarks/overlays/no-pgbouncer.yml` toggles the benchmark stack between the two modes.
- `benchmarks/scenarios/before_pgbouncer_*` produce the before/after numbers.
- `docs/thesis/chapter5_final.md` §5.3.2 is the writeup of the finding.

The `BENCHMARK_DISABLE_PGBOUNCER=1` env var on the benchmark runner inverts overlay selection. Nothing in the production stack reads it.

## Performance characteristics and hotspots

### Efficient by design

- Ingest never blocks on Postgres in the HTTP path; it pushes to Redis and returns 202.
- Dashboard reads come from rollup tables only, with django-redis caching layered on top.
- Compaction writes archives + deletes raw rows in batches per (teacher, week).

### Potential hotspots

- Dashboard page computes some per-student summaries in Python; expensive for very large classes (a 100-student classroom is still fine, but a 1000-student "class" would not be).
- Run replay loads all turns for a single Run into the template at once. Bound: one Run ≈ 20 turns, so fine in practice.
- Some legacy DRF analytics helpers iterate raw rows in Python rather than relying on SQL aggregation; the rollup-only invariant means these are not on the hot path, but they're slow when invoked.

## Safe change guidance

### Changing model fields

- Inspect the django-ninja ingest router for payload validation.
- Inspect `analytics.py` and the rollup commands (`weekly_aggregation.py`, `rollup_incremental.py`, `rebuild_weekly_rollups.py`).
- Inspect admin read-only field lists and filters.
- Inspect dashboard payload assembly in `teacher_statistics_dashboard`.
- If the change touches `Run`/`TurnEvent`, also check `compact_weekly_runs` (the archive shape).

### Changing auth or teacher access

- `apps.py` group permissions.
- `IsTeacher` and any per-view scoping decorators.
- Admin `get_queryset()` and permission overrides.
- Status transition side effects in `models.py`.

### Changing Unity payload shape

- Update the Pydantic models the ninja router validates.
- Update normalization helpers in `views.py` if the legacy path also touches them.
- Update replay parsing in `teacher_run_replay.html`.
- Verify card analytics still parse the stored payload correctly.

## Evidence-backed technical debt

- Legacy and current ingest paths coexist (`insertRunData/` and `runs/ingest/`); only `runs/ingest/` is the canonical Unity target.
- `RunStatistics` still has admin/API surface but the modern dashboard ignores it.
- Some public approval/rejection actions are still GET routes.
- Duplicate-handling logic is inconsistent between forms and database constraints in registration.
- Test coverage is partial — there are real tests for ingestion and rollup accuracy, but registration, admin, and dashboard rendering are not exercised.

## Related docs

- `docs/getting-started.md` — local dev setup.
- `docs/guides/deployment.md` — production bring-up.
- `docs/guides/rollup-runbook.md` — weekly compaction lifecycle.
- `docs/guides/ssl.md` — TLS (self-signed vs Let's Encrypt).
- `docs/guides/ci-cd.md` — GitHub Actions deploy workflow.
- `docs/reference/configuration.md` — every env var.
- `docs/decisions/write-buffering-adr.md` — design of the Redis ingest buffer.
- `docs/thesis/chapter5_final.md` — empirical evaluation, including the PgBouncer-removal finding.
