# AGENTS.md

Repository guidance for coding agents working in this repo.
Scope: repository root and all subdirectories.

## 1. What this repository is

DigitMile is a full-stack product with these major parts:

- `DigitMilePanel/`: Django backend, admin surface, REST endpoints, analytics, weekly rollups, replay archiving, benchmark dataset tooling.
- `DigitMile/`: built Unity WebGL frontend served as static files through nginx.
- `nginx-proxy/`: optional reverse proxy for localhost HTTPS and production-style routing.
- `benchmarks/`: k6-based benchmark and load-testing harness plus scenario runner.
- `k8s/`: Kubernetes manifests — outdated scaffolding, not a live deploy path; treat as placeholder.
- `.github/workflows/`: CI/CD workflows for image build and deployment.

This repo does not contain the editable Unity game source project. `DigitMile/game/` is already-built WebGL output. Treat it as generated/static unless the user explicitly asks to modify deployment-facing frontend assets.

## 2. Canonical docs vs stale docs

When documentation conflicts, use this order of trust:

1. current code,
2. `docs/` (the single documentation folder — see `docs/README.md` for the index),
3. this `AGENTS.md`,
4. the root `README.md` (which is deliberately a short pointer into `docs/`).

Important known drift:

- parts of the hot-week load-testing plan in `docs/decisions/hot-week-load-testing-plan.md` describe work that has since shipped (Slice 1 as of 2026-04-19); the checklist is the accurate status view.
- `docs/decisions/ingest-optimization-plan.md` and `docs/decisions/optimality-metrics-proposal.md` describe work that has **not** shipped; treat them as proposals.

## 3. Repo map

### Top level

- `README.md`: trimmed project overview that links into `docs/`.
- `docker-compose.yml`: primary local runtime.
- `docker-compose.localhost.yml`: local HTTPS/proxy overlay.
- `docker-compose.prod.yml`: production-style image-based overlay.
- `.env`, `.env.example`, `.env.production`, `.env.docker`: environment inputs.
- `docs/`: single source of truth for project documentation. Entry point: `docs/README.md`. Structure: `reference/`, `guides/`, `decisions/`, `research/`.

### Backend

- `DigitMilePanel/manage.py`
- `DigitMilePanel/digitmile/`: Django project package.
- `DigitMilePanel/digitmileapi/`: main application.
- `DigitMilePanel/locale/`: translations.
- `DigitMilePanel/staticfiles/`: collected static output.
- `DigitMilePanel/replay_archives/`: local archive directory when not using mounted volume.

### Frontend runtime assets

- `DigitMile/Dockerfile`
- `DigitMile/nginx.conf`
- `DigitMile/game/index.html`
- `DigitMile/game/Build/`
- `DigitMile/game/TemplateData/`
- `DigitMile/game/i18n/`

### Ops and deployment

- `nginx-proxy/nginx.conf.localhost`
- `nginx-proxy/nginx.conf.production`
- `k8s/` (outdated scaffolding — do not rely on these manifests)
- `.github/workflows/build.yml`
- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-to-environment.yml`

### Benchmarking

- `benchmarks/run_scenario.py`
- `benchmarks/README.md`
- `benchmarks/k6/`
- `benchmarks/scenarios/`
- `benchmarks/reports/`

## 4. Runtime architecture

### Primary local stack

`docker-compose.yml` runs:

- `db`: PostgreSQL 16 (`digitmile-postgres`)
- `backend`: Django + Gunicorn (`digitmile-backend`)
- `frontend`: nginx serving the Unity build (`digitmile-game`)

Optional overlay:

- `docker-compose.localhost.yml` adds `nginx-proxy` for localhost HTTPS and hides direct backend/frontend port exposure.

Production-style overlay:

- `docker-compose.prod.yml` switches backend/frontend/proxy to prebuilt images and mounts persistent replay archive storage.

### Request routing

- frontend game is served at `/`
- Django backend is mounted under `/panel/`
- Django admin is under `/panel/admin/`
- API is under `/panel/api/`

Do not assume `/admin/` or root-level API routes exist.

### Backend startup sequence

The backend container command in `docker-compose.yml` runs, in order:

1. `python manage.py migrate`
2. `python manage.py collectstatic --noinput`
3. `python manage.py create_superuser`
4. `gunicorn digitmile.wsgi:application --bind 0.0.0.0:8000 --workers 3`

## 5. Environment and configuration truths

### Environment file reality

- the active Compose env file is the repo-root `.env`
- `DigitMilePanel/.env.example` explicitly says it is no longer the active env file
- Django settings still call `load_dotenv()` on `DigitMilePanel/.env`

That means environment handling is split. In containerized use, Compose injects env vars directly, so the root `.env` is what matters operationally. Do not assume `DigitMilePanel/.env` is authoritative.

### Important variables used by Django

- `DJANGO_SECRET_KEY`
- `DEBUG`
- `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT`
- `ALLOWED_HOSTS`, `SERVER_IP`
- `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `SITE_URL`
- `GOOGLE_MAPS_API_KEY`
- `REPLAY_ARCHIVE_ROOT`
- `REPLAY_ARCHIVE_COMPRESSION_LEVEL`
- `REPLAY_ARCHIVE_HOT_RETENTION_DAYS`
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`

Known mismatch:

- root `.env.example` still uses `SECRET_KEY`, but `settings.py` reads `DJANGO_SECRET_KEY`.

### Django settings facts

From `DigitMilePanel/digitmile/settings.py`:

- Django 5.2.x
- Python 3.12 in Dockerfiles
- PostgreSQL is the intended database
- WhiteNoise serves static files
- `APPEND_SLASH = False`
- `CORS_ALLOW_ALL_ORIGINS = True`
- supported languages: English, Macedonian, Albanian
- `LOGIN_URL`, `LOGIN_REDIRECT_URL`, and `LOGOUT_REDIRECT_URL` all point to `/panel/`
- no explicit `REST_FRAMEWORK` settings block
- no explicit `CACHES` block

Because `APPEND_SLASH` is disabled, preserve exact route shapes when adding or editing endpoints.

## 6. Backend code structure

Most meaningful backend work happens in `DigitMilePanel/digitmileapi/`.

### Key modules

- `models.py`: domain entities, state transitions, weekly rollup tables, archive metadata.
- `views.py`: Unity ingestion endpoints, registration flows, teacher dashboard, replay, teacher APIs.
- `serializers.py`: DRF serializers for ingestion and teacher APIs.
- `forms.py`: school and teacher registration forms.
- `admin.py`: customized Django admin behavior and teacher scoping.
- `analytics.py`: raw/hot-window analytics helpers over run and turn data.
- `rollup_analytics.py`: historical rollup-backed analytics readers.
- `weekly_rollups.py`: helper logic for rollup math and related utilities.
- `weekly_aggregation.py`: weekly aggregation writer used by compaction/rebuild flows.
- `run_ingestion.py`: canonical ingest normalization and recording-window logic.
- `run_bucket_trends.py`: compact learning-curve trend bucket logic.
- `replay_archives.py`: archive serialization, readback, verification helpers.
- `apps.py`: `post_migrate` hook that provisions the `Teachers` group and permissions.
- `middleware.py`: early health-check middleware.
- `tests.py`: active backend test suite.

### Templates

User-facing backend templates are primarily in `DigitMilePanel/digitmileapi/templates/digitmileapi/`:

- `home.html`
- `register_school.html`
- `register_teacher.html`
- `registration_success.html`
- `pending_registrations.html`
- `teacher_statistics.html`
- `teacher_run_replay.html`

Admin overrides also live under app templates. Teacher-facing UI is largely custom Django-admin and server-rendered HTML, not a separate SPA.

## 7. Core domain model

### Organizational models

- `School`
- `Teacher`
- `TeacherSchoolAssignment`
- `Classroom`
- `Student`

### Gameplay models

- `RunStatistics`: legacy coarse-grained gameplay summary path
- `Run`: canonical per-session gameplay record
- `TurnEvent`: one turn within a run
- `SpecialTileTrigger`: one chained special-tile effect within a turn

### Archive and compaction models

- `ReplayArchive`
- `WeeklyCompactionRun`

### Weekly rollup models already implemented

- `StudentWeekStats`
- `StudentWeekLevelStats`
- `StudentWeekHotspotStats`
- `StudentWeekSpecialTileStats`
- `StudentWeekChainLengthStats`
- `StudentWeekCardFamilyStats`
- `StudentWeekCardTypeStats`
- `StudentRunBucketTrend`
- `StudentWeekConditionalStats`
- `StudentWeekBackCardUsageStats`
- `StudentWeekForeachContextStats`
- `StudentWeekNumberChoiceStats`
- `ClassroomWeekStats`

### Primary implementation truths

- every main domain entity uses prefixed string primary keys, not integer IDs
- the backend still supports both legacy `RunStatistics` and modern `Run`/`TurnEvent`/`SpecialTileTrigger` pipelines
- `Run` rows are retained permanently; turn/trigger rows may be compacted after archival
- `Run.raw_data_compacted_at` marks runs whose raw detailed data has been compacted

## 8. Current business rules that matter

### Teacher and school lifecycle

- `School` and `Teacher` both use `PENDING`, `APPROVED`, and `REJECTED`
- rejection is soft-state, not deletion
- rejecting a teacher deactivates the linked Django user
- rejecting a school can cascade rejection to teachers whose only school is that school
- classrooms, students, runs, and analytics history are preserved on rejection

### Pending teachers are allowed to work

This is one of the most important repo-specific truths.

- teacher self-registration creates a Django staff user immediately
- the user is added to the `Teachers` group immediately
- permission checks allow `PENDING` and `APPROVED` teachers
- only `REJECTED` teachers are blocked

Do not accidentally `fix` this into approval-gated access unless the user explicitly asks for that behavior change. Many flows assume the current model.

### School and classroom relationships

- classrooms belong to teachers and may optionally belong to schools
- classroom creation is constrained so the selected school must be assigned to the teacher
- teacher-scoped admin and APIs exclude rejected schools but still include pending schools

## 9. API and route surface

### Root routing

Defined in `DigitMilePanel/digitmile/urls.py`.

- `/panel/`: home/login
- `/panel/admin/`: Django admin
- `/panel/health/`: URL-level health route
- `/panel/register/school/`
- `/panel/register/teacher/`
- `/panel/registration-success/`
- `/panel/teacher/statistics/`
- `/panel/teacher/statistics/viz-data/`
- `/panel/teacher/runs/<run_id>/`

### API routing

Defined in `DigitMilePanel/digitmileapi/urls.py`.

Important endpoints:

- `/panel/api/fetchCSRFToken/`
- `/panel/api/checkStudentCredentials/`
- `/panel/api/checkClassroomKey/`
- `/panel/api/insertLevelStatistics/` (legacy)
- `/panel/api/insertRunData/` (legacy compatibility)
- `/panel/api/runs/ingest/` (canonical current ingest path)
- `/panel/api/pending-registrations/`
- `/panel/api/approve-school/<school_id>/`
- `/panel/api/reject-school/<school_id>/`
- `/panel/api/approve-teacher/<teacher_id>/`
- `/panel/api/reject-teacher/<teacher_id>/`
- `/panel/api/teacher/students/` via router/viewset
- `/panel/api/teacher/classrooms/`
- `/panel/api/teacher/school/`
- `/panel/api/teacher/run-statistics/`

### Security and transport facts

- Unity/browser CSRF token endpoint is `/panel/api/fetchCSRFToken/`
- Unity is expected to send the token in `X-CSRFToken`
- CORS is fully open in current settings
- some approval/rejection actions are still GET routes

## 10. Ingestion architecture

### Canonical ingest endpoint

Use `/panel/api/runs/ingest/` as the preferred current ingestion path.

Implemented behavior:

- accepts canonical snake_case payloads
- also accepts Unity-style full gameplay payloads
- normalizes into `Run`, `TurnEvent`, and `SpecialTileTrigger`
- preserves idempotent `run_id` behavior
- can derive a deterministic `run_id` when Unity payloads do not provide one
- preserves replay-critical fields such as `place`, `game_map`, and turn metadata
- returns safe duplicate/idempotent success on retries

### Legacy ingest endpoints still present

- `/panel/api/insertRunData/`: older full-fidelity path
- `/panel/api/insertLevelStatistics/`: legacy coarse summary path

Do not remove or silently change these unless the user asks. Current docs treat them as compatibility paths.

### Recording-window policy

Implemented in `run_ingestion.py`.

- the system computes whether a run falls in an open or closed reporting window
- closed-week writes on the canonical ingest path are rejected cleanly with business-level error handling
- this behavior is real and tested

### Gameplay data semantics agents should preserve

- `player_won` is commonly derived from `place == 1`
- `was_correct` means the player selected the correct destination tile implied by the chosen card
- bag number starts at `1` and the chosen number at the end of a turn becomes the next turn's bag number
- number-choice mechanics are primarily relevant to levels 5 and 6
- clown special tile is the backward penalty tile and skateboard is the forward reward tile

## 11. Analytics and dashboard architecture

### Current source of truth

For modern analytics, the main source of truth is:

- `Run`
- `TurnEvent`
- `SpecialTileTrigger`
- weekly rollup tables for compacted history

`RunStatistics` still exists but is not the main teacher dashboard source.

### Analytics layers

- `analytics.py`: reusable raw/hot-window queries and card normalization logic
- dashboard summary logic in `views.py`
- `rollup_analytics.py`: historical rollup-backed reads
- `teacher_statistics.html`: Chart.js-based UI consuming summary JSON and lazy-loaded section data

### Dashboard loading model

- `/panel/teacher/statistics/` renders summary-heavy HTML and JSON blobs
- `/panel/teacher/statistics/viz-data/` lazily loads chart datasets by section
- viz payloads are cached for 7 days (`timeout=604800`) under keys `teacher_stats_viz:*`
- cache backend: `django_redis.cache.RedisCache` pointed at `REDIS_URL` (shared with the ingest write buffer)
- invalidation: `cache.delete_pattern("teacher_stats_viz:*")` in `compact_weekly_runs` and `rebuild_weekly_rollups` — not on every ingest. Dashboard reads reflect the latest completed rollup.

### Learning curves and historical analytics

The refactor described in `docs/decisions/weekly-rollup-prd.md` is not just planned; major pieces already exist:

- weekly rollup tables are real
- replay archives are real
- compaction and verification commands are real
- card-type timing rollups are real
- run-bucket learning curve support is real

Historical analytics are therefore a hybrid of:

- hot recent raw tables
- compacted rollup-backed reads
- archive-backed replay for older runs

## 12. Replay architecture

Replay is served from `/panel/teacher/runs/<run_id>/`.

### Current behavior

- superusers can replay any run
- teachers can replay only runs for their own students
- hot runs can read from relational tables
- compacted runs can read from `ReplayArchive` and archive files on disk
- the template JavaScript does a large amount of replay interpretation client-side

When changing replay-related structures, always inspect all of:

- `views.py`
- `replay_archives.py`
- `teacher_run_replay.html`
- ingest normalization logic
- gameplay analytics that infer card and board semantics

## 13. Registration, auth, and admin workflows

### Registration flows

- school registration uses `SchoolRegistrationForm`
- teacher registration uses `TeacherRegistrationForm`
- registration templates are server-rendered
- school registration uses Google Maps fields and `GOOGLE_MAPS_API_KEY`
- teacher registration supports 1 to 3 schools and per-school years-at-school inputs

### Auth model

- teacher users are Django staff users
- runtime authorization relies on:
  - authenticated user
  - membership in `Teachers` group
  - linked `teacher_profile`
  - teacher status not rejected

### Admin model

This repo heavily customizes Django admin instead of using a separate internal app.

- teachers are scoped to their own classrooms, students, runs, turns, and triggers
- teachers can bulk-create students from classroom admin
- legacy `RunStatistics` admin visibility is effectively superuser-only
- admin save hooks and querysets enforce much of the object-level access behavior

For access-control changes, inspect both API permissions and admin querysets/save permissions.

## 14. Health checks and observability

### Health behavior

`digitmileapi.middleware.HealthCheckMiddleware` intercepts any request whose path contains `health` and returns `{"status": "healthy"}` before normal processing.

This is intentionally broader than a single exact route. Preserve that behavior unless explicitly changing operational probe design.

### Logging

- logging is configured to console/stdout
- newer code paths use structured logger calls
- older paths still contain some `print()`-style behavior

When touching older code, prefer upgrading toward `logger.info()`, `logger.warning()`, `logger.error()`, and `logger.exception()`.

## 15. Management commands

Backend management commands live in `DigitMilePanel/digitmileapi/management/commands/`.

### Core operations

- `create_superuser`
- `setup_teachers_group`
- `clear_school_data`
- `seed_database`

### Archive / rollup / compaction operations

- `compact_weekly_runs`
- `rebuild_weekly_rollups`
- `verify_weekly_rollups`
- `archive_week_replays`
- `verify_replay_archives`

### Benchmark operations

- `prepare_benchmark_dataset`
- `benchmark_teacher_analytics`

### Important destructive command

`clear_school_data` deletes schools, teachers, classrooms, students, runs, triggers, and teacher-linked users. Treat it as destructive; do not run it casually.

## 16. Benchmark and load-testing system

### What is currently implemented

The benchmark pipeline is active and usable now.

- dataset preparation command exists
- analytics baseline benchmarking exists
- Dockerized k6 execution exists
- scenario JSON files exist
- compaction/verification can be orchestrated from benchmark runs
- reports are written under `benchmarks/reports/`

### Current benchmark entrypoints

From repo root:

- `python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json`
- direct k6 scripts in `benchmarks/k6/`

### Benchmark assumptions

- benchmark traffic usually runs from a standalone `grafana/k6` container
- default target is `http://digitmile-backend:8000`
- default host header is `localhost`
- the benchmark runner expects Docker and the running backend container
- benchmark teachers use the known password documented in `benchmarks/README.md`

### Important benchmark caveat

The new hot-week benchmark planning docs describe future work around synthetic benchmark time, anchor weeks, and benchmark-only ingest time overrides. Those docs are not fully implemented yet. Do not assume options like `--anchor-week-start` already exist unless you confirm them in code.

## 17. Tests and validation

### Current backend tests

There is an active test suite in `DigitMilePanel/digitmileapi/tests.py`. Key coverage areas include:

- weekly rollup utilities
- canonical run ingestion
- recording-window policy
- replay archives
- weekly aggregation
- run-bucket trends
- benchmark tooling

Older docs claiming the backend has no real tests are outdated.

### Common test commands

From repo root with Docker running:

- `docker-compose exec backend python manage.py test`
- `docker-compose exec backend python manage.py test digitmileapi`
- `docker-compose exec backend python manage.py test digitmileapi.tests.RunIngestionTests`
- `docker-compose exec backend python manage.py test digitmileapi.tests.RecordingWindowPolicyTests`
- `docker-compose exec backend python manage.py test digitmileapi.tests.WeeklyAggregationTests`
- `docker-compose exec backend python manage.py test digitmileapi.tests.RunBucketTrendTests`
- `docker-compose exec backend python manage.py test digitmileapi.tests.BenchmarkToolingTests`

From `DigitMilePanel/` without Docker, if local deps are installed:

- `python manage.py test`

### Migration checks

When touching models, also run:

- `docker-compose exec backend python manage.py makemigrations --check`

## 18. Common commands

Run these from the repo root unless noted.

### Docker runtime

- start stack: `docker-compose up -d`
- start with localhost HTTPS: `docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d`
- rebuild stack: `docker-compose up -d --build`
- stop stack: `docker-compose down`
- backend logs: `docker-compose logs -f backend`
- all logs: `docker-compose logs -f`

### Backend management

- migrations: `docker-compose exec backend python manage.py migrate`
- Django shell: `docker-compose exec backend python manage.py shell`
- collect static: `docker-compose exec backend python manage.py collectstatic --noinput`
- create superuser interactively: `docker-compose exec backend python manage.py createsuperuser`
- DB shell: `docker-compose exec db psql -U digitmile digitmile`

### Rollups and archives

- compact one week: `docker exec "digitmile-backend" python manage.py compact_weekly_runs YYYY-MM-DD`
- verify one week: `docker exec "digitmile-backend" python manage.py verify_weekly_rollups YYYY-MM-DD --require-archives --verify-run-buckets`
- rebuild one week: `docker exec "digitmile-backend" python manage.py rebuild_weekly_rollups YYYY-MM-DD --update-compaction --rebuild-run-buckets`

### Benchmarks

- prepare dataset: `docker exec "digitmile-backend" python manage.py prepare_benchmark_dataset ...`
- baseline analytics benchmark: `docker exec "digitmile-backend" python manage.py benchmark_teacher_analytics <teacher_id> --iterations 5`
- full scenario: `python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json`

## 19. Deployment and infrastructure notes

### Compose is the most reliable deployment source of truth

For local and production-like behavior, prefer Compose files and current GitHub workflows over older docs.

### CI/CD workflow reality

Primary workflows appear to be:

- `.github/workflows/build.yml`
- `.github/workflows/deploy.yml`
- `.github/workflows/deploy-to-environment.yml`

Older `.github/workflows/django.yml` and `.github/workflows/game.yml` still exist but look less current.

### Kubernetes caveat

Kubernetes manifests exist, but they show some drift from the Compose-based stack and image naming. Treat `k8s/` as secondary unless the user's task is specifically about Kubernetes.

## 20. File-specific guidance by task type

### If changing models or gameplay schema

Review together:

- `DigitMilePanel/digitmileapi/models.py`
- `DigitMilePanel/digitmileapi/serializers.py`
- `DigitMilePanel/digitmileapi/views.py`
- `DigitMilePanel/digitmileapi/analytics.py`
- `DigitMilePanel/digitmileapi/rollup_analytics.py`
- `DigitMilePanel/digitmileapi/weekly_aggregation.py`
- `DigitMilePanel/digitmileapi/tests.py`

### If changing ingestion

Review together:

- `DigitMilePanel/digitmileapi/run_ingestion.py`
- `DigitMilePanel/digitmileapi/serializers.py`
- `DigitMilePanel/digitmileapi/views.py`
- `DigitMilePanel/digitmileapi/tests.py`
- `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_run_replay.html`

### If changing analytics or dashboard behavior

Review together:

- `DigitMilePanel/digitmileapi/analytics.py`
- `DigitMilePanel/digitmileapi/rollup_analytics.py`
- `DigitMilePanel/digitmileapi/weekly_rollups.py`
- `DigitMilePanel/digitmileapi/weekly_aggregation.py`
- `DigitMilePanel/digitmileapi/views.py`
- `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`
- `DigitMilePanel/digitmileapi/tests.py`

### If changing teacher access, registration, or admin flows

Review together:

- `DigitMilePanel/digitmileapi/forms.py`
- `DigitMilePanel/digitmileapi/views.py`
- `DigitMilePanel/digitmileapi/admin.py`
- `DigitMilePanel/digitmileapi/apps.py`
- `DigitMilePanel/digitmileapi/models.py`
- registration and pending-registration templates

### If changing replay/archive/compaction behavior

Review together:

- `DigitMilePanel/digitmileapi/replay_archives.py`
- `DigitMilePanel/digitmileapi/weekly_aggregation.py`
- `DigitMilePanel/digitmileapi/rollup_analytics.py`
- `DigitMilePanel/digitmileapi/run_bucket_trends.py`
- `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py`
- `DigitMilePanel/digitmileapi/management/commands/rebuild_weekly_rollups.py`
- `DigitMilePanel/digitmileapi/management/commands/verify_weekly_rollups.py`
- `DigitMilePanel/digitmileapi/tests.py`

### If changing benchmarks

Review together:

- `benchmarks/run_scenario.py`
- `benchmarks/README.md`
- `benchmarks/k6/`
- `benchmarks/scenarios/`
- `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
- `DigitMilePanel/digitmileapi/management/commands/benchmark_teacher_analytics.py`
- any backend code that benchmark traffic depends on

## 21. Safety and change discipline

### General rules

- keep changes scoped to the user request
- prefer minimal patches over broad refactors
- preserve current public endpoint shapes unless the user asks for contract changes
- preserve `/panel/` mounting assumptions
- preserve pending-teacher access semantics unless intentionally changing that business rule
- treat legacy gameplay endpoints as compatibility surfaces, not dead code
- do not silently break rollup/archive compatibility when changing gameplay data

### Generated or deployment-facing assets

- avoid editing `DigitMile/game/Build/` and similar generated Unity artifacts unless explicitly requested
- avoid editing collected static output in `DigitMilePanel/staticfiles/` unless the task is specifically about collected assets

### Docs updates

If behavior changes materially, update the relevant files under `docs/` (the `reference/` and `guides/` subfolders are the most common targets) and this `AGENTS.md` when appropriate.

## 22. Known sharp edges and contradictions

- root `.env.example` names `SECRET_KEY`; Django reads `DJANGO_SECRET_KEY`
- `docs/decisions/ingest-optimization-plan.md` and `docs/decisions/optimality-metrics-proposal.md` describe work that is not yet in code
- `.github/workflows/django.yml` installs backend deps but does **not** run the test suite; `build-and-push` in that file is dead code (wrong branch guard)
- `k8s/` manifests are outdated scaffolding and do not match the current Compose / workflow reality

## 23. Recommended reading paths for agents

### For backend feature work

1. this `AGENTS.md`
2. `docs/architecture.md`
3. `docs/reference/data-model.md`
4. the relevant backend modules in `DigitMilePanel/digitmileapi/`

### For ingestion/debugging work

1. `docs/reference/ingestion-api.md`
2. `DigitMilePanel/digitmileapi/run_ingestion.py`
3. `DigitMilePanel/digitmileapi/serializers.py`
4. `DigitMilePanel/digitmileapi/views.py`
5. `DigitMilePanel/digitmileapi/tests.py`

### For analytics/dashboard work

1. `docs/reference/analytics-and-dashboard.md`
2. `DigitMilePanel/digitmileapi/analytics.py`
3. `DigitMilePanel/digitmileapi/rollup_analytics.py`
4. `DigitMilePanel/digitmileapi/views.py`
5. `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`

### For registration/admin/auth work

1. `docs/reference/registration-and-admin.md`
2. `DigitMilePanel/digitmileapi/forms.py`
3. `DigitMilePanel/digitmileapi/admin.py`
4. `DigitMilePanel/digitmileapi/views.py`
5. `DigitMilePanel/digitmileapi/apps.py`

### For ops/benchmark/archive work

1. `docs/guides/operations.md`
2. `docs/guides/rollup-runbook.md`
3. `benchmarks/README.md` (linked from `docs/guides/load-testing.md`)
4. relevant management commands (`docs/reference/management-commands.md`) and benchmark scripts

## 24. Bottom line for future agents

This repo is not just a simple Django CRUD app. It is a hybrid of:

- a static Unity WebGL frontend,
- a Django admin-heavy teacher operations backend,
- dual legacy and modern gameplay telemetry pipelines,
- a modern analytics system moving toward weekly rollups and replay archives,
- an operational benchmark harness used to validate ingest, dashboard, replay, compaction, and historical analytics behavior.

Before making non-trivial changes, identify which of those layers your task touches and inspect the related code paths together rather than changing a single file in isolation.
