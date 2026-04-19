# DigitMile

Unity WebGL math game + Django/PostgreSQL backend that ingests per-turn gameplay telemetry and surfaces weekly analytics to teachers.

## Stack

- **Game** — Unity WebGL (`DigitMile/`), served by nginx.
- **Backend** — Django 5.2 + DRF + django-ninja on Python 3.12 (`DigitMilePanel/`), Gunicorn, WhiteNoise.
- **Data** — PostgreSQL 16 behind PgBouncer (transaction pooling). Redis as dashboard cache and ingest write buffer; a `flusher` worker drains the buffer into Postgres.
- **Edge** — nginx reverse proxy with Let's Encrypt (prod) or a self-signed cert (local HTTPS).
- **CI/CD** — GitHub Actions: manual `Deploy to Environment` → build → SSH deploy to the target host.

## Quick start

```bash
cp .env.example .env   # then edit secrets
docker compose up -d
docker compose exec backend python manage.py createsuperuser
```

- Game: http://localhost/
- Teacher / admin: http://localhost:8000/panel/
- Admin: http://localhost:8000/panel/admin/
- Health: http://localhost:8000/panel/health/

See `docs/getting-started.md` for the full walk-through.

## Documentation

All project documentation lives under **[`docs/`](./docs/README.md)**. Top-level entry points:

- [`docs/getting-started.md`](./docs/getting-started.md) — first-time setup.
- [`docs/architecture.md`](./docs/architecture.md) — system overview.
- [`docs/reference/`](./docs/reference/) — data model, ingestion API, analytics, glossary, configuration, management commands.
- [`docs/guides/`](./docs/guides/) — deployment, operations, SSL, i18n, CI/CD, testing, load testing, rollup runbook.
- [`docs/decisions/`](./docs/decisions/) — PRDs, ADRs, plans, task-logs.
- [`docs/research/`](./docs/research/) — thesis-scope research inputs.

## Agent instructions

`AGENTS.md` at the repo root is the authoritative guide for AI agents working in this codebase (Claude Code, Codex, etc.).

## Repository layout

```
DigitMile/                # Unity WebGL build + nginx config (frontend container)
DigitMilePanel/           # Django project (backend + flusher containers)
benchmarks/               # k6 load-testing framework and scenarios
nginx-proxy/              # reverse proxy + TLS configs
scripts/                  # quick-start.sh, init-letsencrypt.sh, setup-nginx-config.sh
.github/workflows/        # CI/CD pipelines
k8s/                      # outdated scaffolding — not a live deploy path
docs/                     # project documentation (this is where new docs go)
docker-compose.yml        # dev stack
docker-compose.localhost.yml, docker-compose.prod.yml  # overlays
```

## License

Not yet specified.
