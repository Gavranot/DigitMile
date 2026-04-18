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

<!-- Phase 2 findings will be appended below this line. -->
