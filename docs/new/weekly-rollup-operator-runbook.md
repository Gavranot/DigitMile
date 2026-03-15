# Weekly Rollup Operator Runbook

Last updated: 2026-03-12

This runbook explains how to operate the weekly-rollup and replay-archive system after the current implementation phase. It also includes a phase-by-phase change map for manual validation.

## Core operations

### Canonical ingest

- Preferred endpoint: `/panel/api/runs/ingest/`
- Accepts both the canonical snake_case payload and the Unity gameplay payload shape used by the legacy endpoint.
- Closed-week writes return `409` with an explicit business message instead of a generic server error.

Manual check:

- send a Unity-style payload to `/panel/api/runs/ingest/`
- verify a `Run`, `TurnEvent`, and `SpecialTileTrigger` set is created
- resend the same payload and verify the response is `200` and no duplicate rows are written

### Compact one week

```bash
docker exec "digitmile-backend" python manage.py compact_weekly_runs YYYY-MM-DD
```

Expected behavior:

- weekly rollups are aggregated
- replay archives are written and verified
- run-bucket trends are rebuilt for affected student/level pairs
- raw turns and triggers are deleted only after verification succeeds

Use `--clear-game-map` only when archive replay payloads are already trusted and you want to reclaim additional storage by removing historical `Run.game_map` payloads after compaction.

### Verify one week

```bash
docker exec "digitmile-backend" python manage.py verify_weekly_rollups YYYY-MM-DD --require-archives --verify-run-buckets
```

Expected behavior:

- summary totals reconcile against raw rows
- card-family, card-type, conditional, number-choice, chain, and trigger totals reconcile
- replay archives exist and checksum verification passes
- historical run-bucket rows reconcile for affected student/level pairs

### Rebuild one week

```bash
docker exec "digitmile-backend" python manage.py rebuild_weekly_rollups YYYY-MM-DD --update-compaction --rebuild-run-buckets
```

Expected behavior:

- weekly rollups are rewritten from current run data for the requested week
- affected historical run-bucket rows are rebuilt
- `WeeklyCompactionRun` can be updated back to `AGGREGATED`

### Benchmarking

Prepare a reproducible dataset:

```bash
docker exec "digitmile-backend" python manage.py prepare_benchmark_dataset \
  --teachers 2 \
  --classrooms-per-teacher 2 \
  --students-per-classroom 12 \
  --weeks 8 \
  --runs-per-student-per-week 3 \
  --avg-turns-per-run 5 \
  --card-mix-profile balanced \
  --bag-level-ratio 0.35 \
  --hot-weeks 2 \
  --clear \
  --output /tmp/benchmark-dataset.json
docker cp "digitmile-backend:/tmp/benchmark-dataset.json" "benchmarks/reports/benchmark-dataset.json"
```

Record a baseline analytics report:

```bash
docker exec "digitmile-backend" python manage.py benchmark_teacher_analytics <teacher_id> \
  --iterations 5 \
  --scenario-name baseline_teacher_analytics \
  --output /tmp/baseline_teacher_analytics.json
docker cp "digitmile-backend:/tmp/baseline_teacher_analytics.json" "benchmarks/reports/baseline_teacher_analytics.json"
```

Run a full Docker-based benchmark scenario:

```bash
python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json
```

Expected behavior:

- dataset preparation runs in `digitmile-backend`
- k6 traffic runs in a standalone Docker container attached directly to the same Docker network as `digitmile-backend`
- default traffic reaches `http://digitmile-backend:8000` from inside that Docker network and sends `Host: localhost`
- reports include latency summaries, request/error highlights, DB relation sizes, archive size snapshots, Docker stats, and compaction/verification outputs

### Archive failure investigation

Check these places first:

- `digitmile-backend` logs for `weekly_compaction_archive_write_result` and `weekly_compaction_archive_verification_result`
- `ReplayArchive.verification_error`
- `verify_weekly_rollups` command output for checksum or metadata failures

Typical action flow:

- rerun `verify_weekly_rollups`
- inspect the archive row for `storage_path`, `checksum_sha256`, and `archive_status`
- if needed, rerun `compact_weekly_runs` or archive-only tooling after restoring the missing file/data

## Phase-by-phase validation map

Each phase below lists the changed files, what changed, and the expected manual behavior.

### Phase 1 - Unity parity on canonical ingest path

- files changed:
  - `DigitMilePanel/digitmileapi/serializers.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/run_ingestion.py`
  - `DigitMilePanel/digitmileapi/tests.py`
  - `docs/new/backend-ingestion-and-api.md`
- changes made:
  - `/panel/api/runs/ingest/` now accepts Unity-style nested payloads and canonical snake_case payloads through one normalization path
  - deterministic `run_id` generation was added for Unity payloads that omit a stable `runId`
  - canonical ingest now persists `place`, `game_map`, clamped elapsed time, normalized card metadata, turns, and triggers with parity to `insertRunData/`
- expected behavior:
  - Unity payloads ingest successfully without using `insertRunData/`
  - retrying the same payload returns safely without duplicate writes
  - replay-critical run and turn metadata matches the legacy endpoint output

### Phase 2 - Closed-week ingest policy

- files changed:
  - `DigitMilePanel/digitmileapi/run_ingestion.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/tests.py`
- changes made:
  - canonical week-close logic was centralized around the authoritative run-finish timestamp
  - ingest now rejects late writes for closed weeks with structured logging and no partial writes
- expected behavior:
  - in-window runs ingest normally
  - late historical runs return `409` with a clear message
  - logs include `run_ingest_closed_week_rejected`

### Phase 3 - Card-type decision-time rollups

- files changed:
  - `DigitMilePanel/digitmileapi/models.py`
  - `DigitMilePanel/digitmileapi/migrations/0006_studentweekcardtypestats.py`
  - `DigitMilePanel/digitmileapi/weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/weekly_aggregation.py`
  - `DigitMilePanel/digitmileapi/rollup_analytics.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`
- changes made:
  - `StudentWeekCardTypeStats` stores raw and clipped decision-time aggregates, extrema, and outlier counts
  - weekly aggregation now writes card-type timing rollups
  - `decision_time_by_card` reads now merge cold rollups with hot raw data and default to clipped averages
- expected behavior:
  - long historical periods still show card-type timing analytics after compaction
  - large outliers no longer dominate teacher-facing averages
  - the existing teacher chart still renders with the new payload shape

### Phase 4 - Run-bucket learning-curve trends

- files changed:
  - `DigitMilePanel/digitmileapi/models.py`
  - `DigitMilePanel/digitmileapi/migrations/0007_studentrunbuckettrend.py`
  - `DigitMilePanel/digitmileapi/run_bucket_trends.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`
- changes made:
  - `StudentRunBucketTrend` stores deterministic 5-run bucket aggregates by student and level
  - learning-curve reads now use stored buckets plus an in-memory hot tail for uncompacted runs
  - level-specific learning trends now derive from bucket points instead of weekly-only history
- expected behavior:
  - semester trends reflect long-horizon learning movement instead of week-by-week noise
  - compacted history still contributes to slope and trend labels
  - newly ingested hot runs still show up at the tail of the trend line

### Phase 5 - Aggregation, compaction, and verification extension

- files changed:
  - `DigitMilePanel/digitmileapi/weekly_aggregation.py`
  - `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py`
  - `DigitMilePanel/digitmileapi/management/commands/rebuild_weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/management/commands/verify_weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/run_bucket_trends.py`
- changes made:
  - compaction now rebuilds affected run-bucket trends and logs all major archive and deletion transitions
  - verification now reconciles card-type, conditional, number-choice, archive, and optional run-bucket coverage
  - raw rows are deleted only after the stronger verification step passes
- expected behavior:
  - compaction fails loudly instead of silently deleting incomplete history
  - verification catches missing archives or mismatched totals
  - rebuild can restore both weekly rollups and historical run buckets for a week

### Phase 6 - Benchmark baseline and Redis gate

- files changed:
  - `DigitMilePanel/digitmileapi/management/commands/benchmark_teacher_analytics.py`
  - `benchmarks/README.md`
- changes made:
  - baseline analytics benchmarking now records p50/p95/p99-style summaries over multiple iterations plus relation sizes and archive size snapshots
  - benchmark execution now has a Docker-native load-generation path that can target the backend container directly on its Docker network
  - Redis was intentionally not added because the new benchmark gate exists and no benchmark evidence yet justifies that operational cost
- expected behavior:
  - operators can collect baseline numbers before making cache decisions
  - no cache layer is introduced unless benchmark evidence later proves it is needed

### Phase 7 - Benchmark and load-test pipeline

- files changed:
  - `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
  - `benchmarks/README.md`
  - `benchmarks/run_scenario.py`
  - `benchmarks/k6/common.js`
  - `benchmarks/k6/ingest.js`
  - `benchmarks/k6/teacher_dashboard.js`
  - `benchmarks/k6/replay.js`
  - `benchmarks/k6/mixed_weekly_cycle.js`
  - `benchmarks/scenarios/hot_only_small.json`
  - `benchmarks/scenarios/mixed_semester_medium.json`
  - `benchmarks/scenarios/mixed_semester_heavy.json`
  - `benchmarks/scenarios/compaction_under_read_load.json`
  - `benchmarks/scenarios/retry_storm_ingest.json`
  - `benchmarks/reports/.gitignore`
  - `.gitignore`
- changes made:
  - dataset preparation now seeds reproducible benchmark teachers, classrooms, students, runs, compactions, and machine-readable reports
  - k6 workloads are parameterized through environment variables and scenario configs
  - scenario runner orchestrates dataset prep, baseline benchmark, Dockerized k6 traffic on the backend Docker network, optional compaction/verification, and final report generation
- expected behavior:
  - the same scenario can be rerun by changing only JSON config
  - reports land under `benchmarks/reports/`
  - traffic generation runs in Docker and exercises the deployed container stack path

### Phase 8 - Documentation and operator guidance

- files changed:
  - `docs/new/backend-ingestion-and-api.md`
  - `docs/new/weekly-rollup-replay-refactor-prd.md`
  - `docs/new/weekly-rollup-replay-schema-spec.md`
  - `docs/new/next-phase-implementation-checklist.md`
  - `docs/new/weekly-rollup-operator-runbook.md`
  - `docs/new/README.md`
- changes made:
  - canonical ingest, rollup progress, benchmark progress, and operator workflows are now documented in one place
  - this runbook adds changed-file maps and expected behavior for each phase to support manual testing
- expected behavior:
  - an engineer can ingest, compact, verify, rebuild, and benchmark from docs alone
  - manual testing can be planned phase by phase without digging through diffs first
