# DigitMile Documentation

DigitMile is a Unity WebGL math game served alongside a Django/PostgreSQL backend that ingests per-turn gameplay telemetry and surfaces weekly analytics to teachers. This folder is the single source of truth for project documentation.

- **Repo root `README.md`** — short overview and pointer into this folder.
- **`AGENTS.md`** at the repo root — instructions for agents (Claude Code, GPT Codex) working in this repo.
- **`benchmarks/README.md`** — kept co-located with the benchmark framework; see `docs/guides/load-testing.md` for the link.

## If you're…

### …new to the project
1. `docs/getting-started.md` — clone, set up `.env`, `docker-compose up`, seed data, log in.
2. `docs/architecture.md` — one-page map of every service.
3. `docs/reference/glossary.md` — hot/cold week, rollup, replay, regret, bag number, card family, etc.

### …adding a feature or a bugfix
- `docs/reference/data-model.md` — every model, every prefixed ID, every unique constraint.
- `docs/reference/ingestion-api.md` — legacy DRF routes and the canonical `POST /panel/api/runs/ingest/`.
- `docs/reference/analytics-and-dashboard.md` — the full analytics pipeline behind the teacher dashboard.
- `docs/reference/registration-and-admin.md` — school / teacher registration and approval workflows.
- `docs/reference/rollup-schema.md` — the `StudentWeek*` rollup tables.
- `docs/reference/run-analytics-models.md` — per-turn ingestion model reference (Run / TurnEvent / SpecialTileTrigger).
- `docs/reference/dashboard-metrics.md` — teacher-facing metric definitions and formulas.
- `docs/reference/configuration.md` — every environment variable the backend reads.
- `docs/reference/management-commands.md` — every `manage.py` command and its flags.

### …deploying or on-calling
- `docs/guides/deployment.md` — bring-up on a fresh server.
- `docs/guides/operations.md` — day-2 operations, PgBouncer, migrations, restarts.
- `docs/guides/ssl.md` — self-signed (local) vs Let's Encrypt (prod).
- `docs/guides/rollup-runbook.md` — weekly compaction, verify, rebuild.
- `docs/guides/ci-cd.md` — how the GitHub Actions workflows are wired.
- `docs/guides/i18n.md` — `makemessages` / `compilemessages` + the language switcher.
- `docs/guides/testing.md` — running the Django test suite.
- `docs/guides/load-testing.md` — pointer to `benchmarks/` and how to run a scenario.

### …looking at design history
`docs/decisions/` — PRDs, ADRs, plans, and task-logs that record *why* parts of the system look the way they do. Stable order of most load-bearing:
- `weekly-rollup-prd.md`
- `write-buffering-adr.md`
- `hardware-sizing.md`
- `ingest-optimization-plan.md` (pending)
- `hot-week-load-testing-plan.md` + `hot-week-load-testing-checklist.md`
- `optimality-metrics-proposal.md` (proposed)
- `dashboard-tasks.md` + `dashboard-visualization-rework.md`
- `next-phase-log.md`

### …looking at research / thesis context
`docs/research/` — the thesis-scope inputs:
- `voved.md` — Macedonian introduction to the platform.
- `north-macedonia-weekly-load-estimate.md` — load-model study that underpins the benchmark scenarios.

## Navigating the folder

```
docs/
├── README.md                    # this file
├── architecture.md              # high-level system overview
├── getting-started.md           # first-time setup
├── reference/                   # spec-style docs (what the code does now)
├── guides/                      # how-to docs (how to do a thing)
├── decisions/                   # ADRs, PRDs, plans, task-logs
└── research/                    # thesis-scope research and background
```

Reference pages describe current behavior. Guides describe how to perform tasks. Decisions capture why something is the way it is. Research is background material that doesn't map to specific code.
