# DigitMile Documentation Audit

**Status:** Phase 1 (Discovery) complete. Phase 2 (Reconciliation) pending approval.
**Branch:** `feat/optimizations`
**Audit date:** 2026-04-18

`AGENTS.md` is intentionally excluded — it is handled separately in Phase 4.

---

## 1. Documentation inventory

Date column = `git log -1 --format=%cI`. Blank = untracked / never committed.

| # | Path | Last committed | Type | Topic (one-line) |
|---|------|----------------|------|------------------|
| 1 | `README.md` | 2025-12-29 | README | Root project overview — architecture diagram, docker-compose quick start, env setup, deploy pointers |
| 2 | `VOVED.md` | *(untracked)* | note (Macedonian) | Introduction / thesis context in Macedonian Cyrillic; motivates the platform and analytics gap |
| 3 | `benchmarks/README.md` | 2026-03-17 | guide | k6 load-testing framework: scenarios, running locally and via `run_scenario.py`, tier definitions |
| 4 | `DigitMilePanel/STATISTICS.md` | 2026-01-01 | reference | Teacher-dashboard statistics definitions (win rate, accuracy, card family accuracy, etc.) |
| 5 | `DigitMilePanel/TASKS.md` | 2026-01-22 | task-list | Phased dashboard feature roadmap (Phase 1–3) |
| 6 | `DigitMilePanel/TASKS-VISUALIZATIONS.md` | 2026-02-15 | task-list | Visualization redesign around `Run` / `TurnEvent` / `SpecialTileTrigger` granular models |
| 7 | `DigitMilePanel/docs/RUN_ANALYTICS_MODELS.md` | 2026-02-15 | reference | Data-model spec for `Run`, `TurnEvent`, `SpecialTileTrigger`, ingestion endpoints |
| 8 | `DigitMilePanel/docs/PRODUCTION_DEPLOYMENT.md` | 2026-02-15 | guide | Production deployment walkthrough (env, UUID prefixes, pool sizing, `SCRIPT_NAME`) |
| 9 | `DigitMilePanel/docs/OPTIMALITY_METRICS.md` | *(untracked)* | note / ADR-ish | Three-way proposal for move-quality metrics (dominated-choice rate, per-turn regret, bag-aware EV) |
| 10 | `docs/old/CI-CD-SETUP.md` | 2026-03-10 | guide | GitHub Actions CI/CD pipeline setup |
| 11 | `docs/old/CLAUDE.md` | 2026-03-17 | note | Older agent instructions for Claude Code |
| 12 | `docs/old/CODEX.md` | 2026-03-17 | note | Older agent instructions for GPT Codex |
| 13 | `docs/old/DATABASE-SETUP.md` | 2026-03-10 | guide | PostgreSQL role and database bootstrap |
| 14 | `docs/old/DEPLOYMENT.md` | 2026-03-10 | guide | Env-var / deploy reference (older) |
| 15 | `docs/old/ENV-FILE-EXPLAINED.md` | 2026-03-10 | reference | Detailed `.env` variable walkthrough |
| 16 | `docs/old/LANGUAGE_SWITCHER_SETUP.md` | 2026-03-10 | guide | i18n setup (mk / en / sq) and language switcher |
| 17 | `docs/old/PRODUCTION-DEPLOYMENT.md` | 2026-03-10 | guide | Full production deploy for `digit.mile.mk` with SSL and Let's Encrypt |
| 18 | `docs/old/QUICK-DEPLOY.md` | 2026-03-10 | quick-ref | Operator cheat-sheet of compose / systemd commands |
| 19 | `docs/old/SETUP-SUMMARY.md` | 2026-03-10 | overview | Older architecture summary |
| 20 | `docs/old/SSL-SETUP.md` | 2026-03-10 | guide | Self-signed vs Let's Encrypt certificate configuration |
| 21 | `docs/old/TASK_PROGRESS.md` | 2026-03-17 | changelog | Progress report on dashboard perf work (late Feb 2026) |
| 22 | `docs/old/TRANSLATION_GUIDE.md` | 2026-03-10 | guide | Django `makemessages` / `compilemessages` workflow |
| 23 | `docs/old/WORKFLOW-CHANGES.md` | 2026-03-10 | changelog | GH Actions workflow refactors |
| 24 | `docs/old/WORKFLOW-FIXES.md` | 2026-03-10 | changelog | Build-context + certbot service fixes |
| 25 | `docs/new/README.md` | 2026-03-17 | index | Index into the `docs/new/` set, reader paths by role |
| 26 | `docs/new/backend-architecture-overview.md` | 2026-03-10 | reference | High-level runtime layout and modules |
| 27 | `docs/new/backend-data-model.md` | 2026-03-10 | reference | Entities, relationships, lifecycle, prefixed-UUID scheme |
| 28 | `docs/new/backend-ingestion-and-api.md` | 2026-03-15 | reference | Ingest API spec (legacy + `runs/ingest`), validation, CSRF |
| 29 | `docs/new/backend-analytics-and-dashboard.md` | 2026-03-10 | reference | Analytics/rollup pipeline and teacher dashboard wiring |
| 30 | `docs/new/backend-registration-and-admin-workflows.md` | 2026-03-10 | reference | School/teacher registration + approval flows |
| 31 | `docs/new/backend-operations-and-config.md` | 2026-03-18 | guide | Django settings, PgBouncer, migrations, ops procedures |
| 32 | `docs/new/glossary.md` | 2026-03-10 | reference | Terminology: hot/cold week, rollup, replay, regret, dominance, etc. |
| 33 | `docs/new/hardware-requirements-report.md` | 2026-03-24 | reference | Capacity analysis from benchmark results |
| 34 | `docs/new/hot-week-load-testing-implementation-plan.md` | 2026-03-17 | plan | Phase 1–9 plan for synthetic-clock hot-week load tests |
| 35 | `docs/new/hot-week-load-testing-execution-checklist.md` | 2026-03-17 | checklist | Milestone checklist for executing the plan above |
| 36 | `docs/new/ingest-performance-optimizations.md` | 2026-03-18 | ADR-ish | Five optimisations to ingest throughput + benchmark protocol |
| 37 | `docs/new/next-phase-implementation-checklist.md` | 2026-03-15 | checklist | Execution guide with phase-gate rules |
| 38 | `docs/new/weekly-rollup-replay-refactor-prd.md` | 2026-03-15 | PRD | PRD for weekly-rollup + replay-archive lifecycle |
| 39 | `docs/new/weekly-rollup-replay-schema-spec.md` | 2026-03-15 | reference | Concrete schema for rollup tables |
| 40 | `docs/new/weekly-rollup-operator-runbook.md` | 2026-03-15 | runbook | Operator commands for compacting / verifying / rebuilding rollups |
| 41 | `docs/new/write-buffering-implementation.md` | 2026-03-25 | reference | Redis ingest-buffer design and flusher daemon |
| 42 | `docs/research/Estimating Weekly System Load for an EdTech Game in North Macedonian Primary Schools.md` | 2026-03-17 | research | Load-modelling study underpinning the national-scale scenarios |

**Excluded from inventory** (vendored / generated / non-doc):
- `DigitMilePanel/.venv/**` — installed Python packages (many LICENSE/README files)
- `DigitMilePanel/staticfiles/admin/**` — Django-contrib admin vendor bundles
- `DigitMilePanel/requirements.txt`, vendor `LICENSE.txt`, dist-info `top_level.txt` — not docs

**Excluded from this phase:** `AGENTS.md` (handled in Phase 4).

---

## 2. Codebase map (ground truth for Phase 2 reconciliation)

### 2.1 Top-level layout

```
DigitMile/                      # Unity WebGL game (static files, nginx container)
DigitMilePanel/                 # Django backend (app: digitmile, API app: digitmileapi)
benchmarks/                     # k6 load tests, scenarios/, run_scenario.py, docker-compose.benchmark.yml
k8s/                            # Kustomize base + overlays/ (dev, prod)
nginx-proxy/                    # Reverse proxy: Dockerfile(.localhost), nginx.conf.production, nginx.conf.localhost, ssl/
scripts/                        # init-letsencrypt.sh, quick-start.sh, setup-nginx-config.sh
workflows_examples/             # Older example workflows (build.yml, deploy.yml, deploy-to-environment.yml)
.github/workflows/              # Active CI: build.yml, deploy.yml, deploy-to-environment.yml, django.yml, game.yml
docs/                           # old/, new/, research/
docker-compose.yml              # dev stack
docker-compose.localhost.yml    # local HTTPS variant
docker-compose.prod.yml         # production overrides
README.md, AGENTS.md, VOVED.md  # root docs
.env, .env.example, .env.docker, .env.production   # env templates
```

### 2.2 Backend — `DigitMilePanel/digitmileapi/`

**Python modules (top-level in `digitmileapi/`):**

| File | Role |
|------|------|
| `models.py` | All Django ORM models |
| `views.py` | Registration + dashboard + legacy ingest views |
| `urls.py` | URL routing for the app |
| `serializers.py` | DRF serializers |
| `admin.py` | Django admin registrations |
| `forms.py` | School / Teacher registration forms with CAPTCHA |
| `middleware.py` | `HealthCheckMiddleware` |
| `apps.py` | Django AppConfig |
| `analytics.py` | Card parsing helpers (`parse_card`, `normalize_card_type`, `card_family_from_name`, `load_level_deck`, `_summary_stats`) |
| `rollup_analytics.py` | Pre-computed rollup queries for the dashboard (win rate by level, decision time by card type, accuracy by family, etc.) |
| `run_bucket_trends.py` | Rolling 5-run bucket trends per level |
| `run_ingestion.py` | Payload normalisation, unix-ms conversion, elapsed clamp, hot-week window check |
| `ingest_schemas.py` | Pydantic schemas for Unity camelCase ingest payload |
| `ingest_router.py` | Django-Ninja router for `POST /panel/api/runs/ingest/` with Redis buffering |
| `replay_archives.py` | Replay-payload build, gzip write/read, SHA-256 verify |
| `weekly_aggregation.py` | Aggregate raw runs into `StudentWeek*` rollup tables |
| `weekly_rollups.py` | Entry point for weekly compaction workflow |
| `test_rollup_accuracy.py`, `tests.py` | Tests |

**Models (see `models.py`) — prefixed-UUID IDs:** `School` (`sch_`), `TeacherSchoolAssignment`, `Teacher` (`tch_`), `Classroom` (`cls_`), `Student` (`stu_`), `RunStatistics` (`rst_`, legacy), `Run` (`run_<hex>`), `TurnEvent` (`trn_`), `SpecialTileTrigger` (`stt_`), `ReplayArchive` (`rar_`), `WeeklyCompactionRun` (`wcr_`), `StudentWeekStats` (`sws_`), `StudentWeekLevelStats` (`swl_`), `StudentWeekHotspotStats` (`swh_`), `StudentWeekSpecialTileStats` (`spt_`), `StudentWeekChainLengthStats` (`scl_`), `StudentWeekCardFamilyStats` (`scf_`), `StudentWeekCardTypeStats` (`sct_`), `StudentRunBucketTrend` (`srb_`), `StudentWeekConditionalStats` (`scd_`), `StudentWeekBackCardUsageStats` (`sbk_`), `StudentWeekForeachContextStats` (`sfc_`), `StudentWeekNumberChoiceStats` (`snc_`), `ClassroomWeekStats` (`cws_`). (Exact field list to be verified in Phase 2 against `models.py`.)

**Migrations (`migrations/`):**
- `0001_initial.py` — core schema (School … SpecialTileTrigger, ReplayArchive)
- `0002_run_game_map_run_place.py`
- `0003_turnevent_bot_positions_after_and_more.py`
- `0004_turnevent_card_metadata.py`
- `0005_weeklycompactionrun_run_raw_data_compacted_at_and_more.py`
- `0006_studentweekcardtypestats.py`
- `0007_studentrunbuckettrend.py`

**Management commands (`management/commands/`)** — to be enumerated exactly in Phase 2 via Glob. Identified so far: `create_superuser`, `flush_ingest_buffer`, `seed_database`, `prepare_benchmark_dataset`, `benchmark_teacher_analytics`, `compact_weekly_runs`, `archive_week_replays`, `clear_school_data`, `rebuild_weekly_rollups`, `setup_teachers_group`, `verify_replay_archives`, `verify_weekly_rollups`.

**API routes (`urls.py`)** — prefix `/panel/`:
- `/`, `/health/`, `/admin/`
- `/api/fetchCSRFToken/`, `/api/checkStudentCredentials/`, `/api/checkClassroomKey/`
- `/api/insertLevelStatistics/`, `/api/insertRunData/` (legacy)
- `/api/runs/ingest/` (Ninja router with Redis buffering)
- Admin-approval APIs: `/api/pending-registrations/`, `/api/approve-school/<id>/`, `/api/reject-school/<id>/`, `/api/approve-teacher/<id>/`, `/api/reject-teacher/<id>/`
- Teacher APIs: `/api/teacher/classrooms/`, `/api/teacher/school/`, `/api/teacher/run-statistics/`, `/api/teacher/students/`
- Registration: `/register/school/`, `/register/teacher/`, `/registration-success/`
- Dashboard: `/teacher/statistics/`, `/teacher/statistics/viz-data/`, `/teacher/runs/<run_id>/`
- i18n: `/i18n/setlang/`

### 2.3 Frontend — `DigitMile/`

- `game/index.html`, `game/Build/{DigitMile.data, DigitMile.framework.js, DigitMile.loader.js, DigitMile.wasm}`, `game/TemplateData/`
- `game/i18n/{en.json, mk.json, sq.json}` — three supported languages
- `nginx.conf` + `Dockerfile`

### 2.4 Benchmarks — `benchmarks/`

- `run_scenario.py` (orchestrator — spins up compose stack, seeds data, runs k6)
- `docker-compose.benchmark.yml` (isolated benchmark stack)
- `scenarios/*.json` (13 files): `bag_conditional_compaction_smoke.json`, `compaction_under_read_load.json`, `hot_only_small.json`, `hot_week_read_write_heavy.json`, `hot_week_read_write_heavy_traffic_only.json`, `ingest_isolation.json`, `mixed_semester_heavy.json`, `mixed_semester_medium.json`, `national_high.json`, `national_medium.json`, `realistic_school_day.json`, `retry_storm_ingest.json`, `stress_ramp.json`
- `k6/` scripts: `common.js`, `ingest.js`, `mixed_weekly_cycle.js`, `replay.js`, `teacher_dashboard.js`
- `reports/` — benchmark output (generated)

### 2.5 Infra & deployment

- `docker-compose.yml` services (expected): `db` (postgres:16-alpine), `redis`, `pgbouncer`, `backend`, `flusher`, `frontend`. Exact service list and env wiring to be verified in Phase 2.
- `docker-compose.localhost.yml` — localhost HTTPS variant
- `docker-compose.prod.yml` — production overrides
- `nginx-proxy/` — `Dockerfile`, `Dockerfile.localhost`, `nginx.conf.production`, `nginx.conf.localhost`, `generate-self-signed-cert.sh`, `ssl/`
- `k8s/base/` and `k8s/overlays/{dev,prod}/` — Kustomize manifests (contents to be verified)
- `.github/workflows/`: `build.yml`, `deploy.yml`, `deploy-to-environment.yml`, `django.yml`, `game.yml`
- `workflows_examples/`: `build.yml`, `deploy.yml`, `deploy-to-environment.yml` (archive — superseded by `.github/workflows/`)
- `scripts/`: `init-letsencrypt.sh`, `quick-start.sh`, `setup-nginx-config.sh`

### 2.6 Config surface

Environment variables read by `digitmile/settings.py` (to be re-verified in Phase 2): `DEBUG`, `DJANGO_SECRET_KEY`, `SERVER_IP`, `ALLOWED_HOSTS`, `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT`, `REDIS_URL`, `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `SITE_URL`, `REPLAY_ARCHIVE_ROOT`, `REPLAY_ARCHIVE_COMPRESSION_LEVEL`, `REPLAY_ARCHIVE_HOT_RETENTION_DAYS`, `BENCHMARK_TIME_OVERRIDE_ENABLED`, `INGEST_BUFFER_BATCH_SIZE`, `INGEST_BUFFER_SLEEP_MS`.

Env files: `.env`, `.env.example`, `.env.docker`, `.env.production` (root), plus `DigitMilePanel/.env`, `.env.example`, `.env.template`.

### 2.7 Build / test / run

- Python 3.12 (from `DigitMilePanel/Dockerfile`).
- `requirements.txt`: django, djangorestframework, django-cors-headers, django-simple-captcha, python-dotenv, psycopg2-binary, whitenoise, gunicorn, django-redis, django-ninja. (Exact versions to be confirmed in Phase 2.)
- Tests: `digitmileapi/tests.py`, `digitmileapi/test_rollup_accuracy.py`.
- Recent dashboard statistics are cached for 7 days with invalidation on run ingest (per the most recent commits `f6dd831`, `017c2f9`).

---

## 3. Next steps

Phase 2 will categorise each doc in the table above as CURRENT / STALE / OUTDATED / MISSING / DUPLICATE, with evidence from the codebase (grep results for referenced symbols, routes, env vars, commands). Findings will be appended to this file as an evidence table. **Nothing will be moved, rewritten, or deleted until you approve that Phase 2 table.**

---

## Phase 2 — Reconciliation findings

Evidence was gathered by (a) reading `settings.py`, `urls.py` (root + app), `ingest_router.py`, `models.py`, `docker-compose*.yml`, `requirements.txt`, and listing `management/commands/`; (b) grep-verifying specific claims from each doc; (c) sampling model fields and URL routes. Full ground-truth snapshot is in Section 2 above.

### 2.a Category definitions
- **CURRENT** — every non-trivial claim I checked matched the code, and no major code feature is silently missing from the doc.
- **OUTDATED** — the doc still describes something that exists, but key claims have drifted (renamed, extended, or superseded). Specific sections need rewriting; the rest can stay.
- **STALE** — the bulk of the doc no longer applies. Content is either superseded by a newer doc or describes features that were never shipped / have been removed.
- **DUPLICATE** — overlaps substantially with another doc and offers no unique information worth preserving independently.

### 2.b Per-file findings

| # | File | Category | Evidence (verified ✓ / refuted ✗) | Recommended action |
|---|------|----------|------------------------------------|---------------------|
| 1 | `README.md` | **OUTDATED** | ✗ Links `./CI-CD-SETUP.md`, `./SSL-SETUP.md`, `./DEPLOYMENT.md` at repo root — these files live in `docs/old/` (broken). ✗ "Services" diagram omits `redis`, `pgbouncer`, and `flusher` (all in `docker-compose.yml`). ✗ Env-var list omits `REDIS_URL`, `REPLAY_ARCHIVE_*`, `INGEST_BUFFER_*`, `BENCHMARK_TIME_OVERRIDE_ENABLED`, `EMAIL_*`, `SITE_URL`, `SERVER_IP`. ✓ Backend Django 5.2 + Gunicorn + WhiteNoise claim. ✓ docker-compose commands work. ✗ No mention of `/panel/` URL prefix in the section that explains routes. | Rewrite into a trim overview that links into `/docs/` — do not preserve the architecture diagram or env-var list as-is. |
| 2 | `VOVED.md` | **CURRENT** | Thesis introduction in Macedonian Cyrillic. Describes motivation, analytics gap, platform goals — no code-level claims to verify. | Move into `docs/` (keep as thesis context). |
| 3 | `benchmarks/README.md` | **CURRENT** | ✓ All 13 scenario JSONs under `benchmarks/scenarios/`. ✓ `run_scenario.py` takes a scenario path arg. ✓ `BENCHMARK_BACKEND_IMAGE` used by `run_scenario.py`; `BENCHMARK_TIME_OVERRIDE_ENABLED` set in `settings.py:248`. ✓ `/panel/health/` endpoint exists. | Move into `docs/guides/load-testing.md`; keep as canonical source for the bench framework. |
| 4 | `DigitMilePanel/STATISTICS.md` | **CURRENT, overlaps** | ✓ Metric formulas (win rate, accuracy, weighted score, improvement, learning curve, consistency) match `rollup_analytics.py` / `run_bucket_trends.py`. Overlaps with `docs/new/backend-analytics-and-dashboard.md` which is broader. | Merge the unique teacher-facing metric definitions into `docs/reference/dashboard-metrics.md`; the broader analytics architecture stays in its own file. |
| 5 | `DigitMilePanel/TASKS.md` | **CURRENT (task-list)** | ✓ Phase 1 items marked [x] are visible in the code (weighted score, learning curve, attention/reward heuristics). Phase 2–3 items still [ ] and genuinely not in the code. | Move to `docs/decisions/` as a historical roadmap artifact or archive — it's a task-list, not product documentation. |
| 6 | `DigitMilePanel/TASKS-VISUALIZATIONS.md` | **CURRENT (task-list)** | ✓ Backend helpers (`win_rate_by_level`, `mistake_hotspots_by_level`, `special_tile_breakdown`, etc.) exist in `rollup_analytics.py`; template wiring is genuinely partial as the doc claims. | Same as #5 — archive as `docs/decisions/dashboard-visualization-rework.md`. |
| 7 | `DigitMilePanel/docs/RUN_ANALYTICS_MODELS.md` | **CURRENT, overlaps** | ✓ Model hierarchy `Run → TurnEvent → SpecialTileTrigger`. ✓ Unique constraints `(run, turn_index)`, `(turn, chain_index)`. ✓ Sentinel `-1 → null` mapping in `run_ingestion.py`. ✓ `/panel/api/runs/ingest/` endpoint & idempotency. Overlaps with `docs/new/backend-data-model.md` + `backend-ingestion-and-api.md`. | Merge unique content into `docs/reference/data-model.md` and `docs/reference/ingestion-api.md`; retire this standalone file. |
| 8 | `DigitMilePanel/docs/PRODUCTION_DEPLOYMENT.md` | **OUTDATED (superseded)** | ✓ Prefix table (`sch_`, `tch_`, etc.) is accurate. ✗ Deployment steps predate PgBouncer integration and the `DB_HOST=db` migration workaround that `docs/new/backend-operations-and-config.md` now documents. ✗ No mention of `flusher` service, Redis buffer, or prod Postgres tuning flags. | Merge residual accurate content into `docs/reference/data-model.md` (the prefix table) and `docs/getting-started.md` / `docs/guides/deployment.md`; delete this file. |
| 9 | `DigitMilePanel/docs/OPTIMALITY_METRICS.md` | **STALE (unimplemented proposal)** | ✗ Proposed module `move_optimality.py` does not exist. ✗ Proposed rollup table `StudentWeekOptimalityStats` not in `models.py`. ✗ Fields `dominated_rate`, `regret`, `ev_regret` not in any model. Grep: only self-reference. | Move to `docs/decisions/optimality-metrics-proposal.md` with a "PROPOSED — not implemented" header. It is a genuine design proposal worth keeping, not a deletion candidate. |
| 10 | `docs/old/CI-CD-SETUP.md` | **STALE (superseded)** | Workflow names line up with `.github/workflows/` at the surface, but env-var and secret lists are incomplete vs today's deploy. Content duplicates what AGENTS.md now documents. | Delete; rewrite the actually-useful CI context (how `.github/workflows/{build,deploy,deploy-to-environment}.yml` interact) into a new `docs/guides/ci-cd.md`. |
| 11 | `docs/old/CLAUDE.md` | **STALE (superseded)** | Directly superseded by `AGENTS.md` (which is authoritative for all agent guidance). Content predates `redis`/`pgbouncer`/`flusher`. | Delete. |
| 12 | `docs/old/CODEX.md` | **STALE (superseded)** | Written for GPT Codex, content merged into `AGENTS.md`. | Delete. |
| 13 | `docs/old/DATABASE-SETUP.md` | **STALE** | Manual `createuser` / `createdb` steps; current stack bootstraps Postgres entirely through `docker-compose.yml` env vars (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`). Internal `digitmile_user` vs `digitmile` inconsistency. | Delete. |
| 14 | `docs/old/DEPLOYMENT.md` | **STALE (superseded)** | Env-var list missing `REDIS_URL`, `REPLAY_ARCHIVE_*`, `INGEST_BUFFER_*`, `BENCHMARK_TIME_OVERRIDE_ENABLED`. No PgBouncer, no flusher. K8s sections are for scaffolding that isn't live. | Delete; `docs/guides/deployment.md` takes over. |
| 15 | `docs/old/ENV-FILE-EXPLAINED.md` | **STALE (incorrect)** | ✗ References `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` — none exist in `settings.py`. ✗ Incomplete env-var coverage as above. | Delete; accurate env-var coverage lives in `docs/getting-started.md` / `docs/reference/configuration.md`. |
| 16 | `docs/old/LANGUAGE_SWITCHER_SETUP.md` | **CURRENT** | ✓ `LocaleMiddleware` at `settings.py:82`. ✓ Languages en/mk/sq at `settings.py:196-201`. ✓ `/i18n/setlang/` route in `digitmile/urls.py:64`. | Move to `docs/guides/i18n.md`. |
| 17 | `docs/old/PRODUCTION-DEPLOYMENT.md` | **STALE (superseded)** | Content overlaps with `docs/new/backend-operations-and-config.md`, `docs/old/SSL-SETUP.md`, and `DigitMilePanel/docs/PRODUCTION_DEPLOYMENT.md`. Missing PgBouncer, Redis, flusher. | Delete; merge any surviving operational trivia into `docs/guides/deployment.md`. |
| 18 | `docs/old/QUICK-DEPLOY.md` | **STALE** | Commands still work at the surface, but internally inconsistent (`digitmile` vs `digitmile_user`) and misses Redis, pgbouncer, flusher setup. | Delete; replace with a short section in `docs/getting-started.md`. |
| 19 | `docs/old/SETUP-SUMMARY.md` | **STALE (superseded)** | Older architecture summary; doesn't include the write-buffer path, PgBouncer, or flusher. | Delete; `docs/architecture.md` replaces it. |
| 20 | `docs/old/SSL-SETUP.md` | **CURRENT** | ✓ `nginx-proxy/generate-self-signed-cert.sh` exists. ✓ `scripts/init-letsencrypt.sh` exists. ✓ Flow matches `docker-compose.localhost.yml` + `docker-compose.prod.yml`. | Move to `docs/guides/ssl.md`. |
| 21 | `docs/old/TASK_PROGRESS.md` | **STALE (historical)** | Worklog of a Feb-2026 dashboard-perf project. Work is reflected in today's rollup tables + `rollup_analytics.py`. No operational value left. | Delete. |
| 22 | `docs/old/TRANSLATION_GUIDE.md` | **CURRENT, overlaps** | ✓ `makemessages` / `compilemessages` workflow; locale dir + `.po` files in `DigitMilePanel/locale/`. Overlaps with `LANGUAGE_SWITCHER_SETUP.md`. | Merge the two into a single `docs/guides/i18n.md`. |
| 23 | `docs/old/WORKFLOW-CHANGES.md` | **STALE (historical)** | Narrates past refactors of the GH Actions workflows. Current workflow truth lives in `.github/workflows/*.yml`. | Delete. |
| 24 | `docs/old/WORKFLOW-FIXES.md` | **STALE (historical)** | Narrates past build-context / certbot bug fixes. Fixes are in `docker-compose.prod.yml` today. | Delete. |
| 25 | `docs/new/README.md` | **CURRENT (index)** | Reading-path index. Will be replaced by the new `docs/README.md` that indexes the consolidated structure. | Delete; new index supersedes. |
| 26 | `docs/new/backend-architecture-overview.md` | **CURRENT** | ✓ Gunicorn 5 workers at `docker-compose.yml:100`. ✓ CSRF endpoint wired. ✓ HealthCheckMiddleware returns `{"status": "healthy"}`. ✓ PgBouncer transaction mode. ✓ Registration flows match `views.py` + `forms.py`. | Move to `docs/architecture.md`. |
| 27 | `docs/new/backend-data-model.md` | **CURRENT** | ✓ Prefixed-ID IDs (`sch_`, `tch_`, `run_`). ✓ Unique constraints verified in `models.py`. ✓ Special-tile semantics (clown -4, skateboard +5). | Move to `docs/reference/data-model.md`. |
| 28 | `docs/new/backend-ingestion-and-api.md` | **CURRENT** | ✓ Both legacy DRF routes and Ninja `/runs/ingest/` verified in `urls.py` + `ingest_router.py`. ✓ Idempotency by `run_id`. ✓ Closed-week rejection at `ingest_router.py:140`. ✓ `elapsed_ms` clamping in `run_ingestion.py`. | Move to `docs/reference/ingestion-api.md`. |
| 29 | `docs/new/backend-analytics-and-dashboard.md` | **CURRENT** | ✓ Card-family enum matches `analytics.py`. ✓ Recency weights (30d→3.0, 90d→2.0, 180d→1.5, older→1.0). ✓ Trend thresholds (±0.05). ✓ Consistency formula. ✓ Cache key format + 300 s TTL. (Note: recent commit `f6dd831` introduced a 7-day caching layer on top of this — document the change.) | Move to `docs/reference/analytics-and-dashboard.md`; add a subsection for the 7-day cache + invalidation on ingest. |
| 30 | `docs/new/backend-registration-and-admin-workflows.md` | **CURRENT** | ✓ Form duplicate checks. ✓ `IsTeacher` permission logic. ✓ Teachers group provisioning via `apps.py` post-migrate. ✓ Approval/rejection transitions. | Move to `docs/reference/registration-and-admin.md`. |
| 31 | `docs/new/backend-operations-and-config.md` | **CURRENT** | ✓ `POOL_MODE=transaction`. ✓ `CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True`. ✓ `DB_HOST=db` migration workaround. ✓ 13 management commands match `management/commands/`. ✓ Env-var list matches `settings.py`. | Move to `docs/guides/operations.md` (split deployment bootstrap into `docs/guides/deployment.md`). |
| 32 | `docs/new/glossary.md` | **CURRENT** | Hot/cold week, rollup, replay, regret, dominance, family, bag, etc. — terms are used consistently in code. | Move to `docs/reference/glossary.md`. |
| 33 | `docs/new/hardware-requirements-report.md` | **CURRENT** | ✓ Gunicorn `2 × vCPU + 1` formula → 5 workers on 2 vCPU. ✓ Benchmark results table + scenario names. ✓ Hardware recommendations derived from benchmark outcomes. | Move to `docs/decisions/hardware-sizing.md` (it is a sized-findings report, not reference). |
| 34 | `docs/new/hot-week-load-testing-implementation-plan.md` | **OUTDATED** | ✗ "Current limitations" claims dataset generation uses real `timezone.now()`, k6 uses `Date.now()`, ingest policy uses real clock — but Milestones A–C have landed (see next row). Phase-list wording is pre-Slice-1. | Move to `docs/decisions/hot-week-load-testing-plan.md` and rewrite the "Current limitations" + "Phases" sections so completed slices read as done. |
| 35 | `docs/new/hot-week-load-testing-execution-checklist.md` | **OUTDATED (minor)** | Checklist itself is accurate; boxes for A1–F1 correctly ticked, F2/F3/G/H correctly open. Just the progress date at the bottom is stale. | Move to `docs/decisions/hot-week-load-testing-checklist.md`; refresh the trailing progress note. |
| 36 | `docs/new/ingest-performance-optimizations.md` | **CURRENT (pending-work)** | ✓ All 5 optimization targets (`offered_cards`, `bot_positions_before`/`_after`, `chosen_card`, `game_map`) still exist in `models.py:470–543` — the proposed work is genuinely outstanding. Baseline numbers at line 287 are still current. | Move to `docs/decisions/ingest-optimization-plan.md` with a clear "NOT YET APPLIED" header. |
| 37 | `docs/new/next-phase-implementation-checklist.md` | **CURRENT (log)** | Foundation work listed as done is in the code (card-type rollups via `StudentWeekCardTypeStats`, closed-week policy, etc.). | Move to `docs/decisions/` as a historical log. |
| 38 | `docs/new/weekly-rollup-replay-refactor-prd.md` | **CURRENT** | ✓ All rollup tables listed exist in `models.py`. ✓ Archive path layout `replay-archives/YYYY/MM/run_<id>.json.gz` in `replay_archives.py`. ✓ `ReplayArchive` status enum (PENDING/READY/FAILED/MISSING/CORRUPT). | Move to `docs/decisions/weekly-rollup-prd.md`. |
| 39 | `docs/new/weekly-rollup-replay-schema-spec.md` | **CURRENT** | ✓ Grain of each `StudentWeek*Stats` table matches `models.py`. ✓ Weekly boundaries (Mon–Sun). | Move to `docs/reference/rollup-schema.md`. |
| 40 | `docs/new/weekly-rollup-operator-runbook.md` | **CURRENT** | ✓ Commands `compact_weekly_runs`, `verify_weekly_rollups`, `rebuild_weekly_rollups` exist with documented flags. ✓ Closed-week 409 contract. | Move to `docs/guides/rollup-runbook.md`. |
| 41 | `docs/new/write-buffering-implementation.md` | **OUTDATED** | File exists (509 lines — the earlier agent claim that it was missing was wrong). ✗ It's framed as a future "implementation plan", but the work has **already landed**: `ingest_router.py:161` does `LPUSH` to `INGEST_BUFFER_REDIS_KEY` and returns 202; `flusher` service in `docker-compose.yml:104`; `flush_ingest_buffer` command in `management/commands/`. | Repurpose as `docs/decisions/write-buffering-adr.md` — rewrite the tense to past ("we chose / we implemented"), drop the "Files to change" section. |
| 42 | `docs/research/Estimating Weekly System Load…md` | **CURRENT (research)** | Research paper; input to the national-scale benchmark scenarios. Nothing to verify against code. | Keep under `docs/research/` (or `docs/decisions/research/`) unchanged. |

### 2.c Gaps (MISSING documentation)

Things present in the code today with no documentation home:

1. **7-day dashboard query cache with invalidation on run ingest** — added in commits `f6dd831` + `017c2f9`. Not mentioned in `backend-analytics-and-dashboard.md`. Evidence: cache layer using `django-redis` (`settings.py:155-163`), invalidation hook on ingest.
2. **`flusher` as an explicit docker-compose service** — introduced by commit `017c2f9`. `docker-compose.yml:104` runs `python manage.py flush_ingest_buffer`. No doc currently calls this out as a service to run.
3. **Consolidated "management commands" reference** — 13 commands in `digitmileapi/management/commands/` with no single reference page; they are scattered across `weekly-rollup-operator-runbook.md`, `hot-week-load-testing-*.md`, and `backend-operations-and-config.md`.
4. **CI/CD current reality** — `.github/workflows/{build,deploy,deploy-to-environment,django,game}.yml` only partially and indirectly documented; `docs/old/CI-CD-SETUP.md` is the only page that tries, and it is stale.
5. **Getting-started path for a new developer** — `scripts/quick-start.sh` exists but no doc page walks through: clone → copy `.env` → `docker-compose up` → `create_superuser` → seed data. Currently scattered across README, old deployment guides, and AGENTS.md.
6. **Test execution** — `digitmileapi/tests.py` and `test_rollup_accuracy.py` exist; no doc explains how to run them locally or in CI.
7. **Benchmark env-var wiring** — `BENCHMARK_BACKEND_IMAGE` and `BENCHMARK_TIME_OVERRIDE_ENABLED` only partially documented in `benchmarks/README.md`; the `run_scenario.py` → `docker-compose.benchmark.yml` wiring isn't laid out anywhere.

These will be filled in Phase 3 using content derived strictly from the code.

### 2.d Overlap / duplicate clusters

| Cluster | Files | Best source of truth |
|---------|-------|----------------------|
| **Deployment / operations** | `docs/new/backend-operations-and-config.md`, `DigitMilePanel/docs/PRODUCTION_DEPLOYMENT.md`, `docs/old/{PRODUCTION-DEPLOYMENT,QUICK-DEPLOY,DEPLOYMENT,SETUP-SUMMARY,DATABASE-SETUP,ENV-FILE-EXPLAINED}.md` | `docs/new/backend-operations-and-config.md` — rest are superseded |
| **SSL** | `docs/old/SSL-SETUP.md`, `docs/old/PRODUCTION-DEPLOYMENT.md` | `docs/old/SSL-SETUP.md` |
| **i18n / translation** | `docs/old/{LANGUAGE_SWITCHER_SETUP,TRANSLATION_GUIDE}.md` | merge into one guide |
| **Data model / ingestion** | `docs/new/backend-data-model.md`, `docs/new/backend-ingestion-and-api.md`, `DigitMilePanel/docs/RUN_ANALYTICS_MODELS.md` | `docs/new/*` are primary; RUN_ANALYTICS_MODELS supplements ingestion API |
| **Statistics / dashboard** | `docs/new/backend-analytics-and-dashboard.md`, `DigitMilePanel/STATISTICS.md`, `DigitMilePanel/TASKS-VISUALIZATIONS.md` | `backend-analytics-and-dashboard.md` is the reference; STATISTICS is a metrics-only subset |
| **Weekly rollup / replay** | `docs/new/weekly-rollup-replay-{refactor-prd,schema-spec}.md` + `weekly-rollup-operator-runbook.md` | Keep all three; they serve distinct reader needs (PRD, schema, runbook) |
| **Load testing** | `benchmarks/README.md`, `docs/new/hot-week-load-testing-{implementation-plan,execution-checklist}.md`, `docs/new/hardware-requirements-report.md`, `docs/new/ingest-performance-optimizations.md` | `benchmarks/README.md` for how to run; others are decisions |
| **Agent instructions** | `AGENTS.md`, `docs/old/{CLAUDE,CODEX}.md` | `AGENTS.md` — rest are superseded |
| **Workflow changelogs** | `docs/old/{WORKFLOW-CHANGES,WORKFLOW-FIXES,CI-CD-SETUP,TASK_PROGRESS}.md` | Delete — current truth is `.github/workflows/` + git history |

### 2.e Proposed target structure for Phase 3

```
docs/
  README.md                                      # index
  getting-started.md                             # new: clone → .env → compose up → superuser → seed
  architecture.md                                # from docs/new/backend-architecture-overview.md
  reference/
    data-model.md                                # from backend-data-model.md + RUN_ANALYTICS_MODELS.md (merged)
    ingestion-api.md                             # from backend-ingestion-and-api.md
    analytics-and-dashboard.md                   # from backend-analytics-and-dashboard.md + STATISTICS.md + 7-day cache note
    registration-and-admin.md                    # from backend-registration-and-admin-workflows.md
    rollup-schema.md                             # from weekly-rollup-replay-schema-spec.md
    configuration.md                             # new: consolidated env-var reference (derived from settings.py)
    management-commands.md                       # new: consolidated command reference (12 commands)
    glossary.md                                  # from glossary.md
  guides/
    deployment.md                                # consolidates backend-operations-and-config.md + SSL-SETUP.md (parts)
    operations.md                                # day-2 ops from backend-operations-and-config.md
    ssl.md                                       # from docs/old/SSL-SETUP.md
    i18n.md                                      # merged LANGUAGE_SWITCHER_SETUP + TRANSLATION_GUIDE
    rollup-runbook.md                            # from weekly-rollup-operator-runbook.md
    load-testing.md                              # from benchmarks/README.md (stays linked from benchmarks/)
    ci-cd.md                                     # new: reflects .github/workflows/ today
    testing.md                                   # new: how to run tests locally & in CI
  decisions/
    weekly-rollup-prd.md                         # from weekly-rollup-replay-refactor-prd.md
    hardware-sizing.md                           # from hardware-requirements-report.md
    hot-week-load-testing-plan.md                # from hot-week-load-testing-implementation-plan.md (updated)
    hot-week-load-testing-checklist.md           # from hot-week-load-testing-execution-checklist.md (refreshed)
    ingest-optimization-plan.md                  # from ingest-performance-optimizations.md
    write-buffering-adr.md                       # rewritten from write-buffering-implementation.md (past tense)
    next-phase-log.md                            # from next-phase-implementation-checklist.md
    optimality-metrics-proposal.md               # from DigitMilePanel/docs/OPTIMALITY_METRICS.md
    dashboard-metrics-roadmap.md                 # merged DigitMilePanel/TASKS.md + TASKS-VISUALIZATIONS.md
  research/
    north-macedonia-weekly-load-estimate.md      # renamed research paper

README.md                                        # trimmed root README, links into docs/
VOVED.md                                         # kept at root as the Macedonian thesis intro, or moved under docs/research/
AGENTS.md                                        # handled in Phase 4
docs/research/                                   # (if kept separate from docs/decisions/research/)
```

Files I plan to **delete** in Phase 3:
- `docs/old/CLAUDE.md`, `docs/old/CODEX.md`
- `docs/old/CI-CD-SETUP.md`, `docs/old/DEPLOYMENT.md`, `docs/old/DATABASE-SETUP.md`, `docs/old/ENV-FILE-EXPLAINED.md`, `docs/old/PRODUCTION-DEPLOYMENT.md`, `docs/old/QUICK-DEPLOY.md`, `docs/old/SETUP-SUMMARY.md`, `docs/old/TASK_PROGRESS.md`, `docs/old/WORKFLOW-CHANGES.md`, `docs/old/WORKFLOW-FIXES.md`
- `DigitMilePanel/docs/PRODUCTION_DEPLOYMENT.md` (after salvaging the prefix table into `docs/reference/data-model.md`)
- `docs/new/README.md` (new `docs/README.md` supersedes)
- the now-empty `docs/old/` and `DigitMilePanel/docs/` directories

Files that **stay in place, untouched**:
- `AGENTS.md` (Phase 4)
- `benchmarks/README.md` (kept at the framework it describes; `docs/guides/load-testing.md` is a one-paragraph pointer)
- `VOVED.md` (root-level thesis intro; user choice whether to move — I'll flag in Phase 3)

### 2.f Open questions for the user before Phase 3

1. **`VOVED.md`** — keep at repo root as thesis-facing intro, or move to `docs/research/voved.md`?
2. **`DigitMilePanel/{STATISTICS,TASKS,TASKS-VISUALIZATIONS}.md`** — absorb fully into `docs/` (my default), or keep them in `DigitMilePanel/` as panel-local docs close to the Django app?
3. **Task-lists / roadmaps** (`DigitMilePanel/TASKS.md`, `TASKS-VISUALIZATIONS.md`, `next-phase-implementation-checklist.md`) — do you want these preserved as historical ADRs under `docs/decisions/`, or are they disposable work-in-progress notes that can be deleted?
4. **`docs/research/` folder** — keep as `docs/research/` or nest under `docs/decisions/research/`?

If you don't care about any of these, I'll go with the defaults shown in the tree above.

