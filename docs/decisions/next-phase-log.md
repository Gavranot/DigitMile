# Next Phase Implementation Checklist

Last updated: 2026-03-12

## Why this document exists

This checklist is the execution guide for the next implementation phase of the weekly-rollup and replay-archive refactor.

It is written for coding agents and engineers who need:

- a strict implementation order,
- explicit acceptance criteria,
- clear progress tracking rules,
- concrete file targets,
- operational logging expectations,
- benchmark and validation requirements.

This document is meant to be followed step by step. It assumes the current foundation already exists:

- weekly rollup tables,
- replay archive metadata and archive helpers,
- weekly compaction command,
- initial rollup-backed analytics,
- initial verification and benchmark helper commands.

## Agent Operating Rules

Any agent implementing this phase must follow these rules.

### Before starting any checklist item

- read this file fully,
- read `docs/decisions/weekly-rollup-prd.md`,
- read `docs/reference/rollup-schema.md`,
- inspect the current implementation status in the touched files,
- do not assume earlier checklist items are fully complete without verifying them.

### While implementing

- keep changes small and isolated by checklist item,
- preserve current working functionality unless the checklist explicitly replaces it,
- prefer extending the new architecture instead of adding more logic to legacy paths,
- preserve replay correctness over optimization,
- preserve idempotency on ingestion and compaction paths,
- add logging for all state transitions and rejected writes,
- add or update tests for every meaningful behavior change.

### After completing a checklist item

- update the progress log section in this file,
- update the implementation progress section in `docs/decisions/weekly-rollup-prd.md`,
- update the implementation progress section in `docs/reference/rollup-schema.md` if schema or read-path coverage changed,
- run the relevant verification commands and tests,
- note any caveats left behind.

## Progress Tracking Protocol

This file must be updated as work progresses.

### Status values

- `not_started`
- `in_progress`
- `blocked`
- `completed`

### Required progress update fields

For each major item, append or update:

- `status`
- `date`
- `owner`
- `files changed`
- `tests run`
- `commands run`
- `notes`
- `follow-ups`

### Required implementation logging

Every agent must add or preserve structured logging for:

- ingest accept,
- ingest duplicate/idempotent return,
- ingest rejected due to closed recording window,
- compaction start,
- compaction aggregation result,
- archive write result,
- archive verification result,
- compaction delete result,
- rebuild start and completion,
- verification mismatch failures,
- benchmark scenario start and completion.

### Progress log template

Use this format for each completed or active item:

```md
### Item <id> - <title>
- status: <not_started|in_progress|blocked|completed>
- date: YYYY-MM-DD
- owner: <agent or engineer name>
- files changed:
  - `path/one.py`
  - `path/two.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test ...`
- commands run:
  - `docker exec "digitmile-backend" python manage.py ...`
- notes:
  - ...
- follow-ups:
  - ...
```

## High-Level Implementation Order

The recommended order is mandatory unless a strong technical reason exists to change it.

1. Extend `/panel/api/runs/ingest/` to full Unity parity.
2. Add closed-week ingest policy and logging.
3. Add compact historical card-type rollups.
4. Add compact run-bucket trend points for learning curves.
5. Extend aggregation and compaction to populate the new rollups and trends.
6. Cut over `decision_time_by_card` and learning-curve reads.
7. Add stronger verification and reconciliation coverage.
8. Add real k6-based benchmark pipeline and scenario configs.
9. Optionally add Redis caching after baseline measurements exist.

Do not start Redis work before the benchmark pipeline exists, unless there is a blocking operational reason.

## Phase 1 - Full Unity Parity on `/panel/api/runs/ingest/`

### Goal

Make `/panel/api/runs/ingest/` the canonical Unity ingestion endpoint with full behavioral parity to `insertRunData/`, while preserving idempotency and retry safety.

### Required implementation tasks

#### 1.1 Extend serializer contract

Target files:

- `DigitMilePanel/digitmileapi/serializers.py`

Required changes:

- extend `RunIngestionSerializer` so it can represent the full Unity payload currently accepted by `UnityRunUploadPayloadSerializer`,
- support Unity-equivalent fields for:
  - `place`,
  - `game_map`,
  - `runStartedUnixMs`,
  - `runEndedUnixMs`,
  - Unity turn field naming parity or a translation layer,
- preserve validation for:
  - turn ordering,
  - chain ordering,
  - correct/wrong move consistency,
  - student existence,
  - number sentinel conversion.

Acceptance criteria:

- the serializer can validate a Unity-style full-fidelity run payload without using `insertRunData/`.

#### 1.2 Extend `RunIngestionView`

Target files:

- `DigitMilePanel/digitmileapi/views.py`

Required changes:

- store `place`,
- store `game_map`,
- derive `player_won` from `place == 1` when Unity payload uses that form,
- derive and clamp elapsed time with the same behavior currently used in `InsertRunDataView`,
- preserve `transaction.atomic()`,
- preserve idempotent `run_id` behavior,
- preserve race-condition-safe duplicate handling,
- preserve bulk creation of turn events and triggers,
- preserve card normalization and metadata extraction parity with `insertRunData/`.

Acceptance criteria:

- Unity can send the same gameplay payload semantics to `/panel/api/runs/ingest/`,
- duplicate retries return safely without double insertion,
- replay-critical fields are preserved.

#### 1.3 Prepare legacy endpoint deprecation

Target files:

- `docs/reference/ingestion-api.md`
- `docs/decisions/weekly-rollup-prd.md`

Required changes:

- document that `/panel/api/runs/ingest/` is the preferred canonical path,
- document that `insertRunData/` is legacy compatibility until Unity migration is complete.

Acceptance criteria:

- docs clearly direct future work toward `/runs/ingest/`.

### Tests required

- serializer tests for full Unity parity payload,
- view tests for successful ingest,
- idempotent retry tests,
- race-condition duplicate tests if practical,
- regression tests comparing key persisted fields against the old endpoint behavior.

## Phase 2 - Closed-Week Ingest Policy

### Goal

Prevent late statistical writes for a closed reporting week without surfacing generic server errors.

### Required implementation tasks

#### 2.1 Add ingest recording-window policy helper

Target files:

- `DigitMilePanel/digitmileapi/` new helper module or existing utility module

Required behavior:

- define the canonical school-week boundary,
- define close time, for example Friday 20:00 server time,
- derive the run's logical week from the authoritative run-finish timestamp,
- determine whether recording is open or closed for that week.

Acceptance criteria:

- one helper determines week-open vs week-closed status consistently.

#### 2.2 Enforce policy on `/panel/api/runs/ingest/`

Target files:

- `DigitMilePanel/digitmileapi/views.py`

Required behavior:

- reject writes for closed weeks,
- return a clear business response such as:
  - `409` or `422`,
  - message explaining that statistics recording is closed until the next week,
- log the rejection with structured context,
- do not write partial data.

Acceptance criteria:

- late runs are rejected cleanly,
- logs make the reason explicit,
- valid in-window runs still ingest successfully.

### Tests required

- allowed ingest before cutoff,
- rejected ingest after cutoff,
- week-boundary edge case tests,
- timezone-sensitive behavior tests if project timezone handling makes this necessary.

## Phase 3 - Card-Type Decision-Time Rollups

### Goal

Make `decision_time_by_card` meaningful across long historical periods without depending on raw historical turns.

### Required schema

Add `StudentWeekCardTypeStats`.

Recommended fields:

- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `card_type`
- `chosen_count`
- `decision_time_sum_ms`
- `decision_time_count`
- `decision_time_sum_sq_ms`
- `decision_time_min_ms`
- `decision_time_max_ms`
- `clipped_decision_time_sum_ms`
- `clipped_decision_time_sum_sq_ms`
- `outlier_count`

### Required implementation tasks

#### 3.1 Add schema and migration

Target files:

- `DigitMilePanel/digitmileapi/models.py`
- new migration file under `DigitMilePanel/digitmileapi/migrations/`

Acceptance criteria:

- the new rollup model exists with appropriate uniqueness and indexes.

#### 3.2 Add outlier policy helper

Target files:

- `DigitMilePanel/digitmileapi/weekly_rollups.py` or a nearby analytics utility module

Required behavior:

- define a clipping policy for decision times,
- preserve raw values,
- compute clipped values for teacher-facing charts,
- count how many observations were clipped.

Recommended default:

- hard clip values above a configurable ceiling such as `120000` ms,
- keep both raw and clipped aggregates.

Acceptance criteria:

- outliers do not dominate teacher-facing average trends.

#### 3.3 Extend weekly aggregation

Target files:

- `DigitMilePanel/digitmileapi/weekly_aggregation.py`

Required behavior:

- aggregate chosen card type statistics into `StudentWeekCardTypeStats`,
- populate raw and clipped sufficient statistics,
- preserve count and extrema.

Acceptance criteria:

- compacted history retains card-type timing analytics.

#### 3.4 Add rollup-backed reader

Target files:

- `DigitMilePanel/digitmileapi/rollup_analytics.py`
- `DigitMilePanel/digitmileapi/views.py`

Required behavior:

- replace raw-history `decision_time_by_card` with rollup + hot-data hybrid logic,
- return:
  - semester aggregate values,
  - weekly time-series values per card type,
- default charts to clipped averages,
- optionally expose outlier counts in payload if useful.

Acceptance criteria:

- compacted historical data still contributes to `decision_time_by_card`,
- teachers can inspect long-term card-type timing patterns.

### Tests required

- aggregation correctness,
- clipped vs raw behavior,
- compacted-history read correctness,
- hot + cold mixed-history merge correctness.

## Phase 4 - Run-Bucket Trend Points For Learning Curves

### Goal

Provide semester-wide pedagogically meaningful learning curves without replaying all raw history.

### Required schema

Add `StudentRunBucketTrend`.

Recommended grain:

- `student + level + bucket_index`
- one bucket per 5 runs

Recommended fields:

- `student`
- `classroom`
- `teacher`
- `level`
- `bucket_index`
- `bucket_size_runs`
- `first_run_created_at`
- `last_run_created_at`
- `run_count`
- `wins`
- `correct_moves`
- `wrong_moves`
- `score_sum`
- `score_count`
- `score_sum_sq`
- `elapsed_sum_ms`
- `elapsed_count`
- `elapsed_sum_sq`

### Required implementation tasks

#### 4.1 Add schema and migration

Target files:

- `DigitMilePanel/digitmileapi/models.py`
- new migration file under `DigitMilePanel/digitmileapi/migrations/`

Acceptance criteria:

- run-bucket trend model exists with efficient lookup indexes.

#### 4.2 Add bucket-building logic

Target files:

- new trend-builder helper module or `DigitMilePanel/digitmileapi/weekly_aggregation.py`

Required behavior:

- build ordered run buckets of 5 runs per student and level,
- aggregate sufficient statistics into each bucket,
- support rebuild from hot raw runs,
- support historical read merging with current hot runs.

Important design rule:

- bucket index must be deterministic,
- rebuilding must not create bucket drift.

Acceptance criteria:

- one student's long history compresses into compact ordered trend points.

#### 4.3 Cut over learning-curve and improvement reads

Target files:

- `DigitMilePanel/digitmileapi/views.py`

Required behavior:

- replace weekly-only historical trend semantics with run-bucket trend semantics,
- compute:
  - semester learning slope,
  - trend label,
  - improvement rate,
  - level-specific trends,
- preserve hot recent runs by either:
  - merging them into the tail of the bucket sequence, or
  - building an in-memory partial bucket for current hot runs.

Acceptance criteria:

- teacher-facing learning curves behave like long-horizon pedagogical trends, not just weekly summaries.

### Tests required

- bucket assignment tests,
- trend-slope correctness over synthetic histories,
- mixed compacted + hot trend series tests,
- level-specific trend tests.

## Phase 5 - Aggregation and Compaction Extension

### Goal

Ensure compaction populates all new historical analytics structures before raw rows are deleted.

### Required implementation tasks

#### 5.1 Extend weekly aggregation outputs

Target files:

- `DigitMilePanel/digitmileapi/weekly_aggregation.py`

Required behavior:

- include new weekly card-type rollups,
- if chosen, update or trigger run-bucket trend generation for newly compacted weeks,
- preserve current rollup writes.

Acceptance criteria:

- compaction week output includes all new historical metrics.

#### 5.2 Extend compaction verification

Target files:

- `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py`
- `DigitMilePanel/digitmileapi/management/commands/verify_weekly_rollups.py`

Required behavior:

- verify:
  - weekly summary totals,
  - chain totals,
  - trigger totals,
  - card-family totals,
  - conditional totals,
  - number-choice totals,
  - card-type totals,
  - archive presence and checksum,
- fail compaction before deletion if verification does not pass.

Acceptance criteria:

- compaction cannot silently delete data when rollups or archives are incomplete.

### Tests required

- compaction succeeds on valid week,
- compaction fails on verification mismatch,
- archive verification failure blocks deletion,
- card-type totals reconcile.

## Phase 6 - Historical Query Optimization and Optional Redis

### Goal

Keep historical teacher queries fast under realistic concurrent load.

### Required implementation tasks

#### 6.1 First measure without Redis

Target files:

- benchmark tooling only

Rule:

- do not add Redis before baseline benchmark numbers exist.

Acceptance criteria:

- baseline latency and storage reports exist.

#### 6.2 Add Redis cache only if justified

Target files:

- `DigitMilePanel/digitmile/settings.py`
- Docker compose files
- teacher stats read paths

Recommended cache targets:

- `teacher_statistics_viz_data`
- dashboard summary payloads
- closed-week or closed-range historical payloads

Required behavior:

- cache compacted historical responses longer than hot current-week responses,
- invalidate or refresh when compaction completes,
- do not use cache as a source of truth.

Acceptance criteria:

- benchmark proves a meaningful read-latency gain,
- operational complexity stays manageable.

## Phase 7 - Benchmark and Load-Test Pipeline

### Goal

Create a realistic, parameterized benchmark pipeline that simulates week-by-week system use.

### Tooling decision

Use `k6`.

### Required directory structure

Add a top-level benchmark area such as:

- `benchmarks/README.md`
- `benchmarks/scenarios/`
- `benchmarks/k6/`
- `benchmarks/reports/` (gitignored if desired)

### Required benchmark components

#### 7.1 Dataset preparation command

Target files:

- new management command under `DigitMilePanel/digitmileapi/management/commands/`

Required parameters:

- `--teachers`
- `--classrooms-per-teacher`
- `--students-per-classroom`
- `--weeks`
- `--runs-per-student-per-week`
- `--avg-turns-per-run`
- `--card-mix-profile`
- `--bag-level-ratio`
- `--compact-weeks`
- `--hot-weeks`
- `--clear`

Required behavior:

- seed a realistic dataset,
- optionally compact selected weeks,
- verify archives and rollups,
- emit a machine-readable report of what was created.

Acceptance criteria:

- one command can prepare benchmark state reproducibly.

#### 7.2 k6 workload scripts

Required scripts:

- `benchmarks/k6/ingest.js`
- `benchmarks/k6/teacher_dashboard.js`
- `benchmarks/k6/replay.js`
- `benchmarks/k6/mixed_weekly_cycle.js`

Required parameterization:

- concurrent gameplay writers,
- concurrent teacher users,
- traffic duration,
- request mix,
- hot vs cold replay ratio,
- grade/classroom filter usage,
- cache warm vs cold runs.

Suggested environment variables:

- `BASE_URL`
- `SESSION_COOKIE` or authenticated teacher credentials strategy
- `VUS_PLAYERS`
- `VUS_TEACHERS`
- `DURATION`
- `INGEST_RPS`
- `DASHBOARD_RPS`
- `VIZ_RPS`
- `REPLAY_RPS`
- `HOT_REPLAY_RATIO`
- `GRADE_FILTER_RATIO`
- `CLASSROOM_FILTER_RATIO`
- `SCENARIO_NAME`

Acceptance criteria:

- benchmark traffic can be changed without editing script source.

#### 7.3 Mixed weekly-cycle scenario

Required behavior:

- simulate ingest during a synthetic school week,
- simulate teacher dashboard usage during and after gameplay,
- run compaction at the end of the synthetic week,
- verify archives and rollups,
- run post-compaction analytics and replay traffic,
- emit one report containing:
  - latency summaries,
  - error counts,
  - table sizes,
  - archive size,
  - compaction time.

Acceptance criteria:

- one scenario can model realistic week-by-week system behavior.

#### 7.4 Scenario config files

Required example scenario configs:

- `hot_only_small.json`
- `mixed_semester_medium.json`
- `mixed_semester_heavy.json`
- `compaction_under_read_load.json`
- `retry_storm_ingest.json`

Each scenario must define:

- dataset shape,
- compacted week count,
- traffic shape,
- load duration,
- verification behavior,
- report output location.

### Metrics to capture

The benchmark pipeline must record:

- p50/p95/p99 latency by endpoint,
- request rates,
- error rates,
- backend CPU,
- backend memory,
- DB CPU,
- DB memory,
- DB relation sizes,
- archive directory size,
- compression ratio,
- compaction duration,
- archive verification result,
- rollup verification result.

### Benchmark success criteria

- the same scenario can be rerun with only config changes,
- compacted historical queries are materially faster than baseline raw-history reads,
- replay still works under mixed hot/cold conditions,
- compaction and verification can be exercised under realistic data volume.

## Phase 8 - Documentation and Operator Runbook

### Goal

Ensure the system is operable by future agents and humans.

### Required implementation tasks

- update `docs/reference/ingestion-api.md` to reflect canonical Unity ingest path,
- update the PRD progress section,
- update the schema spec progress section,
- add a runbook under `docs/new/` describing:
  - how to ingest,
  - how to compact,
  - how to verify,
  - how to rebuild,
  - how to benchmark,
  - how to read archive failure logs,
  - when `--clear-game-map` should be used.

Acceptance criteria:

- an agent unfamiliar with the prior conversation can operate the system from docs alone.

## Implementation Sequence Checklist

Use this quick checklist when executing.

- [x] Phase 1.1 Extend serializer contract for `/runs/ingest/`
- [x] Phase 1.2 Extend `RunIngestionView` for full Unity parity
- [x] Phase 1.3 Document canonical ingest path
- [x] Phase 2.1 Add recording-window helper
- [x] Phase 2.2 Enforce closed-week policy on ingest path
- [x] Phase 3.1 Add `StudentWeekCardTypeStats`
- [x] Phase 3.2 Add clipped outlier handling for decision times
- [x] Phase 3.3 Extend weekly aggregation for card types
- [x] Phase 3.4 Cut over `decision_time_by_card`
- [x] Phase 4.1 Add `StudentRunBucketTrend`
- [x] Phase 4.2 Add deterministic 5-run bucket builder
- [x] Phase 4.3 Cut over learning-curve reads to trend buckets
- [x] Phase 5.1 Extend aggregation/compaction to new structures
- [x] Phase 5.2 Extend verification checks
- [x] Phase 6.1 Record benchmark baseline without Redis
- [x] Phase 6.2 Add Redis only if benchmark justifies it
- [x] Phase 7.1 Add dataset preparation command
- [x] Phase 7.2 Add parameterized k6 scripts
- [x] Phase 7.3 Add mixed weekly-cycle scenario
- [x] Phase 7.4 Add scenario config files
- [x] Phase 8 Add operator docs and runbook

## Current Progress Log

### Item foundation - Weekly rollup and replay archive base
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `DigitMilePanel/digitmileapi/models.py`
  - `DigitMilePanel/digitmileapi/replay_archives.py`
  - `DigitMilePanel/digitmileapi/weekly_aggregation.py`
  - `DigitMilePanel/digitmileapi/rollup_analytics.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/tests.py`
  - `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py`
  - `DigitMilePanel/digitmileapi/management/commands/rebuild_weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/management/commands/verify_weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/management/commands/benchmark_teacher_analytics.py`
  - `docs/decisions/weekly-rollup-prd.md`
  - `docs/reference/rollup-schema.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
  - `docker exec "digitmile-backend" python manage.py makemigrations --check`
- commands run:
  - `docker exec "digitmile-backend" python manage.py compact_weekly_runs ...`
  - `docker exec "digitmile-backend" python manage.py rebuild_weekly_rollups ...`
  - `docker exec "digitmile-backend" python manage.py verify_weekly_rollups ...`
- notes:
  - base weekly rollups, archive flow, and initial historical read cutover are in place.
  - `decision_time_by_card` and pedagogically stronger learning curves are still pending.
- follow-ups:
  - complete Phases 1 through 8 in this checklist.

### Item 1 - Unity parity on canonical ingest path
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `DigitMilePanel/digitmileapi/serializers.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/run_ingestion.py`
  - `DigitMilePanel/digitmileapi/tests.py`
  - `docs/reference/ingestion-api.md`
  - `docs/decisions/weekly-rollup-prd.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.RunIngestionTests digitmileapi.tests.RecordingWindowPolicyTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.RunIngestionTests digitmileapi.tests.RecordingWindowPolicyTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- notes:
  - `/panel/api/runs/ingest/` now accepts full Unity payloads and canonical snake_case payloads through one normalization path.
  - canonical ingest now persists `place`, `game_map`, clamped elapsed time, normalized card metadata, turns, and special triggers with idempotent retry behavior.
  - Unity payloads without a usable `runId` are normalized to a deterministic content-derived `run_id` for safe retries.
- follow-ups:
  - migrate Unity clients from `insertRunData/` to `/panel/api/runs/ingest/` when ready.

### Item 2 - Closed-week ingest policy
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/run_ingestion.py`
  - `DigitMilePanel/digitmileapi/tests.py`
  - `docs/decisions/weekly-rollup-prd.md`
  - `docs/reference/rollup-schema.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.RunIngestionTests digitmileapi.tests.RecordingWindowPolicyTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.RunIngestionTests digitmileapi.tests.RecordingWindowPolicyTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- notes:
  - one helper now computes canonical week boundaries, Friday 20:00 close time, and open-vs-closed recording status from the authoritative run-finish timestamp.
  - closed-week ingest attempts return `409` with an explicit business message and do not write partial run data.
  - structured logs now cover ingest accept, duplicate/idempotent returns, and closed-week rejection context.
- follow-ups:
  - align compaction targeting and any future rebuild/reconciliation tooling with the same recording-window policy helper.

### Item 3 - Card-type decision-time rollups
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `DigitMilePanel/digitmileapi/models.py`
  - `DigitMilePanel/digitmileapi/migrations/0006_studentweekcardtypestats.py`
  - `DigitMilePanel/digitmileapi/weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/weekly_aggregation.py`
  - `DigitMilePanel/digitmileapi/rollup_analytics.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`
  - `DigitMilePanel/digitmileapi/tests.py`
  - `docs/decisions/weekly-rollup-prd.md`
  - `docs/reference/rollup-schema.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.RunBucketTrendTests digitmileapi.tests.WeeklyAggregationTests digitmileapi.tests.RunIngestionTests digitmileapi.tests.RecordingWindowPolicyTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `docker exec "digitmile-backend" python manage.py makemigrations digitmileapi`
  - `docker exec "digitmile-backend" python manage.py makemigrations --check`
  - `docker exec "digitmile-backend" python manage.py migrate`
- notes:
  - `StudentWeekCardTypeStats` now preserves raw and clipped decision-time sufficient statistics, extrema, and outlier counts.
  - weekly aggregation now writes card-type rollups and `decision_time_by_card` reads from rollups plus hot data.
  - teacher charts now consume the new clipped-by-default card-type payload shape while staying backward-compatible with the existing chart render path.
- follow-ups:
  - expose weekly series and outlier counts more explicitly in the teacher UI if product work wants a richer chart experience.

### Item 4 - Run-bucket learning-curve trends
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `DigitMilePanel/digitmileapi/models.py`
  - `DigitMilePanel/digitmileapi/migrations/0007_studentrunbuckettrend.py`
  - `DigitMilePanel/digitmileapi/run_bucket_trends.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`
  - `DigitMilePanel/digitmileapi/tests.py`
  - `docs/decisions/weekly-rollup-prd.md`
  - `docs/reference/rollup-schema.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.RunBucketTrendTests digitmileapi.tests.WeeklyAggregationTests digitmileapi.tests.RunIngestionTests digitmileapi.tests.RecordingWindowPolicyTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `docker exec "digitmile-backend" python manage.py makemigrations digitmileapi`
  - `docker exec "digitmile-backend" python manage.py makemigrations --check`
  - `docker exec "digitmile-backend" python manage.py migrate`
- notes:
  - `StudentRunBucketTrend` now stores deterministic 5-run trend buckets keyed by student, level, and bucket index.
  - learning-curve reads now use bucket trend points plus in-memory hot-run tail merging instead of week-only historical summaries.
  - teacher learning-curve selectors now accept smaller bucket-series histories so compacted semester trends remain visible.
- follow-ups:
  - consider adding explicit bucket labels in the UI to distinguish bucket points from single-run attempts.

### Item 5 - Aggregation, compaction, and verification extension
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `DigitMilePanel/digitmileapi/weekly_aggregation.py`
  - `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py`
  - `DigitMilePanel/digitmileapi/management/commands/rebuild_weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/management/commands/verify_weekly_rollups.py`
  - `DigitMilePanel/digitmileapi/run_bucket_trends.py`
  - `DigitMilePanel/digitmileapi/tests.py`
  - `docs/decisions/weekly-rollup-prd.md`
  - `docs/reference/rollup-schema.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.RunBucketTrendTests digitmileapi.tests.WeeklyAggregationTests digitmileapi.tests.RunIngestionTests digitmileapi.tests.RecordingWindowPolicyTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `docker exec "digitmile-backend" python manage.py makemigrations digitmileapi`
  - `docker exec "digitmile-backend" python manage.py makemigrations --check`
  - `docker exec "digitmile-backend" python manage.py migrate`
- notes:
  - compaction now logs start, aggregation, archive write/verify, run-bucket rebuild, and delete results with structured context.
  - compaction now rebuilds affected historical run-bucket rows and verifies archives plus run-bucket coverage before deleting raw rows.
  - weekly verification now reconciles card-family, card-type, conditional, number-choice, summary, archive, and optional run-bucket totals.
- follow-ups:
  - add explicit failure-mode tests for archive corruption and verification mismatch blocking once benchmark/dataset tooling lands.

### Item 6 - Benchmark baseline and Redis gate
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `DigitMilePanel/digitmileapi/management/commands/benchmark_teacher_analytics.py`
  - `benchmarks/README.md`
  - `docs/decisions/weekly-rollup-prd.md`
  - `docs/reference/rollup-schema.md`
  - `docs/decisions/next-phase-log.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.BenchmarkToolingTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `docker exec "digitmile-backend" python manage.py benchmark_teacher_analytics <teacher_id> --iterations 2 --scenario-name manual_baseline`
  - `python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json`
- notes:
  - baseline analytics benchmarking now records latency summaries, relation sizes, and archive size snapshots over multiple iterations.
  - benchmark traffic generation now runs in Docker on the backend container network with explicit request host-header control.
  - Redis caching was intentionally deferred because the new benchmark gate exists and no current benchmark result justifies the added operational complexity yet.
- follow-ups:
  - evaluate Redis only after medium/heavy scenario reports show a meaningful bottleneck on compacted historical reads.

### Item 7 - Dataset prep and k6 benchmark pipeline
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
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
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests.BenchmarkToolingTests`
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `docker exec "digitmile-backend" python manage.py prepare_benchmark_dataset --teachers 1 --classrooms-per-teacher 1 --students-per-classroom 2 --weeks 2 --runs-per-student-per-week 1 --avg-turns-per-run 3 --card-mix-profile balanced --bag-level-ratio 0.3 --hot-weeks 1 --clear`
  - `python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json`
- notes:
  - one dataset-preparation command now seeds reproducible benchmark state and can compact historical weeks as part of setup.
  - k6 scripts are parameterized with environment variables and scenario JSON files rather than hard-coded request settings.
  - the scenario runner now orchestrates dataset prep, baseline benchmarking, Dockerized k6 traffic on the backend Docker network, optional compaction, verification, and one consolidated report.
- follow-ups:
  - add larger saved benchmark report artifacts outside git if you want historical trend tracking over multiple runs.

### Item 8 - Operator runbook and manual validation docs
- status: completed
- date: 2026-03-12
- owner: OpenAI agent
- files changed:
  - `docs/guides/rollup-runbook.md`
  - `docs/reference/ingestion-api.md`
  - `docs/decisions/weekly-rollup-prd.md`
  - `docs/reference/rollup-schema.md`
  - `docs/README.md`
  - `docs/decisions/next-phase-log.md`
- tests run:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`
- commands run:
  - `python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json`
  - `docker exec "digitmile-backend" python manage.py verify_weekly_rollups YYYY-MM-DD --require-archives --verify-run-buckets`
- notes:
  - the runbook now documents ingest, compaction, verification, rebuild, benchmarking, archive troubleshooting, and `--clear-game-map` guidance.
  - each phase now has a manual validation map listing changed files, what changed, and expected behavior for hand testing.
- follow-ups:
  - keep the phase validation map updated whenever new rollup or benchmark behavior changes land.
