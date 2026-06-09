# DigitMile

A scalable web platform for **pedagogical analytics** of a Unity WebGL math game played by primary-school students. Built as an undergraduate thesis project at FINKI/UKIM (Skopje) targeting national-scale deployment in North Macedonia (~60,000 grade 4–6 students) on a single 2 vCPU / 3.8 GiB VPS.

The platform turns raw per-turn gameplay telemetry into weekly teacher-facing analytics — win rates, accuracy by card family, decision time, learning-curve trends, and identification of students who need extra help.

## What's in the repo

| Component | Path | Purpose |
|---|---|---|
| **Game** | `DigitMile/` | Unity WebGL build served by nginx |
| **Backend** | `DigitMilePanel/` | Django 5.2 — REST API, ingest endpoint, teacher dashboard, admin |
| **Flusher** | `DigitMilePanel/digitmileapi/management/commands/flush_ingest_buffer.py` | Long-running worker that drains the Redis ingest buffer into PostgreSQL in batches |
| **Compactor** | `compactor/` | Cron container that fires the Friday weekly compaction (20:00 Europe/Skopje) |
| **Edge** | `nginx-proxy/` | Reverse proxy with Let's Encrypt (prod) or self-signed cert (local HTTPS) |
| **Benchmarks** | `benchmarks/` | k6 load-testing harness, isolated Docker stack, scenario catalogue, toggle harness for before/after comparisons |
| **Docs** | `docs/` | Single source of truth for documentation (see `docs/README.md`) |
| **Thesis** | `docs/thesis/` | Thesis manuscript (Macedonian) |

## Architecture

```
┌──────────────┐          ┌─────────────┐         ┌────────────┐
│ Unity WebGL  │  POST    │  Django     │  LPUSH  │   Redis    │
│   client     │ ────────▶│  + ninja    │────────▶│ ingest_    │
│  (browser)   │  ingest  │  + Pydantic │  202    │  buffer    │
└──────────────┘          └─────────────┘         └─────┬──────┘
                                 │                      │ LRANGE
                                 │ reads from           │ + LTRIM
                                 ▼ rollup tables        ▼
                          ┌──────────────┐       ┌─────────────┐
                          │ Teacher      │       │   Flusher   │
                          │ dashboard    │       │   worker    │
                          │ (cached)     │       │ (batch=50)  │
                          └──────┬───────┘       └──────┬──────┘
                                 │                      │ bulk_create
                                 │                      │ in one txn
                                 ▼                      ▼
                          ┌────────────────────────────────────┐
                          │   PostgreSQL 16 (direct, CONN_MAX_AGE=60)
                          │   • Run / TurnEvent / SpecialTileTrigger (hot)
                          │   • StudentWeek* / ClassroomWeek* (rollups)
                          │   • ReplayArchive (cold)
                          └────────────────────────────────────┘
                                       ▲
                                       │ Friday 20:00 EET
                                       │ POST /api/internal/compaction/
                                ┌──────┴───────┐
                                │  Compactor   │
                                │  (cron)      │
                                └──────────────┘
```

**Why this shape:** the HTTP ingest path validates the payload (Pydantic v2) and pushes to Redis in ~3 ms, returning `202 Accepted`. The flusher drains in batches, amortizing PostgreSQL round-trips. The dashboard reads exclusively from precomputed rollup tables — never from raw `TurnEvent` rows — so dashboard latency stays bounded as the dataset grows. Weekly compaction archives raw rows to compressed JSONL and deletes them, keeping the hot tables small.

## Stack

- **Game** — Unity WebGL → static nginx container
- **Backend** — Python 3.12, Django 5.2, django-ninja + Pydantic v2 (ingest), DRF (legacy panels), Gunicorn (5 workers), WhiteNoise
- **Data** — PostgreSQL 16 (direct connection, tuned for write-heavy throughput: `synchronous_commit=off`, raised `shared_buffers`), Redis 7 (ingest buffer + django-redis dashboard cache with 7-day TTL and invalidation on ingest)
- **Edge** — nginx reverse proxy, Let's Encrypt via certbot webroot, auto-renew every 12h
- **Infra** — Docker Compose, multi-environment overlays (`docker-compose.localhost.yml`, `docker-compose.prod.yml`)
- **CI/CD** — GitHub Actions: manual `Deploy to Environment` → build → push to Docker Hub → SSH deploy
- **i18n** — Macedonian, Albanian, English

## Performance (production-target hardware: 2 vCPU / 3.8 GiB VPS)

All five non-functional requirements from the thesis pass with significant margin. Numbers below are from the k6 benchmark harness against an isolated production-mirror Docker stack on the target VPS.

| Requirement | Target | Measured | Margin |
|---|---|---|---|
| Sustain 11 RPS ingest × 15 min | p95 < 1000 ms, ≤ 0.5% drops, CPU < 90% | p95 **28.9 ms**, 0 drops, CPU 27.7% | 34× |
| Absorb 60 s burst at 44 RPS (high-adoption lesson-bell) | p95 < 2000 ms, 0 5xx | p95 **24.5 ms**, 0 drops | 81× |
| Dashboard p95 under combined 15 RPS load | < 3000 ms | **675 ms** (student dashboard) | 4.4× |
| Friday weekly compaction (per teacher-week) | << 58 h maintenance window | **~21.5 s** | very large |
| Recovery from 2× overload (22 RPS for 5 min) | back to baseline p95 in 2 min | no measurable degradation | — |

**Cumulative effect of optimizations** (pre-everything baseline vs current tree, identical hardware): average HTTP latency **22 683 ms → 29 ms (-99.9%)**, dropped iterations **920 → 0**.

The thesis evaluation chapter walks through each of six shipped optimizations (PgBouncer pooling, PG tuning, rollup-only analytics, Redis dashboard cache, django-ninja ingest, Redis write buffer) and reports marginal contributions. One notable finding: **PgBouncer was removed from production** after the benchmark surfaced a negative interaction with the Redis write buffer — its per-request handshake cost exceeded the pooling savings once the ingest path stopped touching PostgreSQL synchronously.

Full breakdown in `docs/thesis/chapter5_final.md`; raw reports under `benchmarks/server_reports/`.

## Quick start

```bash
cp .env.example .env   # edit secrets — DB_PASS, DJANGO_SECRET_KEY, INTERNAL_API_TOKEN, etc.
docker compose up -d
docker compose exec backend python manage.py createsuperuser
```

- Game: http://localhost/
- Teacher / admin panel: http://localhost:8000/panel/
- Django admin: http://localhost:8000/panel/admin/
- Health: http://localhost:8000/panel/health/

For HTTPS on `localhost` see `docs/guides/ssl.md`. For production deployment with Let's Encrypt: `docs/guides/deployment.md`.

## Running a benchmark

```bash
python benchmarks/run_scenario.py benchmarks/scenarios/realistic_school_day.json
```

This spins up an isolated Docker Compose stack (separate Postgres, Redis, backend, flusher), seeds a benchmark dataset, runs the k6 traffic script, optionally triggers compaction, and writes a full JSON report. The harness supports overlays (`benchmarks/overlays/`) to revert individual optimizations and baseline Docker images to revert code-level changes — used to produce the before/after numbers in the thesis. See `benchmarks/README.md`.

## Documentation

All documentation lives under [`docs/`](./docs/README.md). High-traffic entry points:

- [`docs/getting-started.md`](./docs/getting-started.md) — full local setup walkthrough
- [`docs/architecture.md`](./docs/architecture.md) — one-page system map
- [`docs/reference/`](./docs/reference/) — data model, ingestion API, analytics pipeline, configuration, management commands, glossary
- [`docs/guides/`](./docs/guides/) — deployment, operations, SSL, CI/CD, i18n, load testing, rollup runbook
- [`docs/decisions/`](./docs/decisions/) — ADRs and design history (write-buffering, capacity model, benchmark plan)
- [`docs/research/`](./docs/research/) — capacity model, national load estimate, compaction scale notes
- [`docs/thesis/`](./docs/thesis/) — thesis manuscript

`AGENTS.md` at the repo root is the authoritative guide for AI agents (Claude Code, Codex) working in this codebase.

## License

Not yet specified.
