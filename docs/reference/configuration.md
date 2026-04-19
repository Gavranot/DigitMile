# Configuration Reference

All environment variables read by the Django backend. Every `os.getenv(...)` call in `DigitMilePanel/digitmile/settings.py` is listed here. If a value is not listed, it is hardcoded — assume *not* configurable without a code change.

The root `.env` file is the single source of truth in all deployed modes; `docker-compose.yml` loads it via `env_file:` for `backend` and `flusher`, and the `db` container reads `POSTGRES_*` from the same file. The legacy `DigitMilePanel/.env` exists for some older tooling paths but is not what the compose stack uses.

## Core Django

| Variable | Default | Purpose |
|----------|---------|---------|
| `DJANGO_SECRET_KEY` | *(insecure dev default in `settings.py`)* | Django `SECRET_KEY`. Always set in any non-throwaway deployment. |
| `DEBUG` | `"True"` | `True`/`False` string; `DEBUG = True` is insecure and must be `"False"` in production. |
| `ALLOWED_HOSTS` | `"digit.mile.mk,localhost,127.0.0.1"` | Comma-separated host list. |
| `SERVER_IP` | *(unset)* | If set, appended to `ALLOWED_HOSTS`. |
| `SITE_URL` | `"http://localhost:8000"` | Used in email link generation (password resets, approval emails). |

Hardcoded (not env-driven): `CSRF_TRUSTED_ORIGINS = ["https://digit.mile.mk"]`, `CORS_ALLOW_ALL_ORIGINS = True`, `APPEND_SLASH = False`, `SECURE_PROXY_SSL_HEADER`.

## Database (PostgreSQL via PgBouncer)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_NAME` | *(required)* | Database name. |
| `DB_USER` | *(required)* | Database user. |
| `DB_PASS` | *(required)* | Database password. |
| `DB_HOST` | *(required)* | Normally `pgbouncer` in the docker-compose stack; `db` for migrations. |
| `DB_PORT` | `5432` | Integer or blank. Non-numeric values fall back to Django's default. |

Django is configured with `CONN_MAX_AGE = 0` and `DISABLE_SERVER_SIDE_CURSORS = True` because PgBouncer is in transaction-pooling mode; this is not env-configurable.

## Redis

| Variable | Default | Purpose |
|----------|---------|---------|
| `REDIS_URL` | `"redis://localhost:6379/1"` | Used by both the django-redis cache and the ingest write buffer. Docker-compose sets this to `redis://redis:6379/1` at runtime. |

## Email

| Variable | Default | Purpose |
|----------|---------|---------|
| `EMAIL_BACKEND` | `django.core.mail.backends.console.EmailBackend` | Dev default writes to stdout; override for SMTP. |
| `EMAIL_HOST` | `smtp.gmail.com` | |
| `EMAIL_PORT` | `587` | |
| `EMAIL_USE_TLS` | `"True"` | |
| `EMAIL_HOST_USER` | `""` | |
| `EMAIL_HOST_PASSWORD` | `""` | |
| `DEFAULT_FROM_EMAIL` | `"noreply@digitmile.com"` | Sender for approval / rejection emails. |

## Replay archives

| Variable | Default | Purpose |
|----------|---------|---------|
| `REPLAY_ARCHIVE_ROOT` | `<BASE_DIR>/replay_archives` | Disk path for gzipped replay payloads. Compose mounts `replay_archives_data:/var/lib/digitmile/replay-archives`. |
| `REPLAY_ARCHIVE_COMPRESSION_LEVEL` | `6` | gzip level 0–9. |
| `REPLAY_ARCHIVE_HOT_RETENTION_DAYS` | `7` | Days before raw `TurnEvent` / `SpecialTileTrigger` rows are eligible for deletion after archival. |

## Ingest write buffer

| Variable | Default | Purpose |
|----------|---------|---------|
| `INGEST_BUFFER_BATCH_SIZE` | `50` | Max items the `flusher` pops per iteration. |
| `INGEST_BUFFER_SLEEP_MS` | `100` | Idle sleep between flushes when the queue is empty. |

The Redis key name (`"ingest_buffer"`) is hardcoded as `INGEST_BUFFER_REDIS_KEY` in `settings.py` — not env-configurable.

## Benchmark-only

| Variable | Default | Purpose |
|----------|---------|---------|
| `BENCHMARK_TIME_OVERRIDE_ENABLED` | `"False"` | When `"True"`, the ingest endpoint honors the `X-Benchmark-Reference-Time` HTTP header for the recording-window check. Must be `False` in production. |

The benchmark runner also reads two variables from the root `.env` that are **not** consumed by Django:

- `BENCHMARK_BACKEND_IMAGE` — Docker image tag the benchmark stack uses for its backend/flusher. Set by `deploy.yml` to `<dockerhub-user>/digitmile-backend:<TARGET_ENV>-latest`; locally, re-tag the built image as `digitmile-backend:latest` or set this variable to match.
- `BENCHMARK_KEEP_STACK` — set to `"1"` to leave the benchmark compose stack running after a scenario finishes (useful when debugging).

## Superuser bootstrap

Read by the `create_superuser` management command, which runs on every `backend` container start:

- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_PASSWORD`
- `DJANGO_SUPERUSER_EMAIL`

If any of the three is unset, the command logs a warning and skips creation.

## Google Maps (registration)

`GOOGLE_MAPS_API_KEY` — consumed by the school-registration form template for the address-picker. Not present in `settings.py` directly; it is referenced from the template context.

## What the CI pipeline writes

`.github/workflows/deploy.yml` assembles `.env` on the target server from repo **secrets** (credentials) and **vars** (non-secrets). Canonical set:

- Secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `DB_USER`, `DB_PASS`, `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SECRET_KEY`, `EMAIL_HOST_PASSWORD`, `GOOGLE_MAPS_API_KEY`, per-env `{ENV}_SSH_PRIVATE_KEY`.
- Vars: `DB_HOST`, `DB_NAME`, `DB_PORT`, `SITE_URL`, `ALLOWED_HOSTS`, `SERVER_IP`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_BACKEND`, `EMAIL_USE_TLS`, `DEBUG`, `DOMAIN`, `SSL_EMAIL`, per-env `{ENV}_HOST`, `{ENV}_USERNAME`, `{ENV}_PORT`.
