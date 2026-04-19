# Hot-Week Load Testing Execution Checklist

Last updated: 2026-04-19 (status refresh); original: 2026-03-15.

This checklist turns `docs/decisions/hot-week-load-testing-plan.md` into an implementation-ready worklist.

> **Status as of 2026-04-19:** Slice 1 (A1–A3, B1–B2, C1–C2, D1–D2, E1, F1) is marked `[x]` below, verified against the codebase. Docker-based end-to-end verification was deferred at the time Slice 1 shipped; re-run it before starting Slice 2. Slices 2 and 3 remain open.

## Context for fresh agents

This file assumes you do not have conversation context from earlier work. Read the files below before changing code.

### Required reading order

1. `docs/decisions/hot-week-load-testing-plan.md`
   - the target design, missing capabilities, and intended implementation order.
2. `docs/guides/rollup-runbook.md`
   - the current operator-facing benchmark path and the per-phase changed-file map.
3. `docs/decisions/next-phase-log.md`
   - confirms which weekly-rollup and benchmark foundation pieces are already implemented.
4. `benchmarks/README.md`
   - documents the current Docker-native benchmark path and current scenario/report conventions.

### Source files you must inspect before implementation

- `benchmarks/run_scenario.py`
  - current orchestration flow, scenario parsing, Docker-network k6 invocation, and report generation.
- `benchmarks/scenarios/*.json`
  - current config surface and how scenario inputs are expressed.
- `benchmarks/k6/common.js`
- `benchmarks/k6/ingest.js`
- `benchmarks/k6/teacher_dashboard.js`
- `benchmarks/k6/replay.js`
- `benchmarks/k6/mixed_weekly_cycle.js`
  - current traffic model, timestamp generation, request headers, and concurrency limitations.
- `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
  - current dataset seeding behavior and dataset report schema.
- `DigitMilePanel/digitmileapi/run_ingestion.py`
- `DigitMilePanel/digitmileapi/views.py`
  - current ingest path and recording-window enforcement.
- `DigitMilePanel/digitmileapi/tests.py`
  - existing protections for ingest, weekly rollups, and benchmark tooling.

### Crucial things to understand before you start

- canonical Unity-compatible ingest on `/panel/api/runs/ingest/` is already implemented.
- closed-week ingest rejection is already implemented for normal behavior.
- this checklist is about making benchmark traffic realistic and reproducible, not redesigning the production ingest contract.
- the current benchmark runner already uses Dockerized k6 on the backend Docker network, targeting `http://digitmile-backend:8000` with `Host: localhost`.
- the current `hot_only_small` scenario is a smoke test, not true concurrent hot-week pressure.
- the biggest current gap is time semantics: dataset prep and k6 payloads still depend too much on real current time.
- any benchmark-only ingest-time override must be explicitly gated so production requests remain unchanged.
- benchmark reports must separate expected business outcomes like intentional `409` closed-week rejections from genuine failures.

## How to use this file

- work top to bottom unless a dependency note says otherwise,
- keep changes scoped to one ticket where possible,
- after each completed ticket:
  - run the listed verification,
  - update the status marker,
  - note any caveats left behind.

## Current progress note

- 2026-03-16: Slice 1 code changes were implemented for A1-A3, B1-B2, C1-C2, D1-D2, E1, and F1.
- Static verification passed for the touched Python, JavaScript, and scenario JSON files.
- Docker-based verification is still pending because the Docker daemon was unavailable in the current environment during implementation.

## Status markers

- `[ ]` not started
- `[~]` in progress
- `[x]` completed
- `[!]` blocked

## Milestone A - Synthetic benchmark time

### A1 - Add anchor-week configuration to dataset prep
- status: `[x]`
- files:
  - `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
- tasks:
  - add `--anchor-week-start YYYY-MM-DD`
  - stop deriving benchmark weeks from `timezone.now()`
  - validate the supplied date and normalize it to Monday week start
- acceptance:
  - same seed + same anchor week always produce the same week layout
  - different current dates do not change the generated benchmark week schedule
- verify:
  - `docker exec "digitmile-backend" python manage.py prepare_benchmark_dataset ... --anchor-week-start 2026-02-16`

### A2 - Emit synthetic clock metadata in dataset report
- status: `[x]`
- files:
  - `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
- tasks:
  - add report fields:
    - `anchor_week_start`
    - `hot_week_start`
    - `hot_week_end`
    - `synthetic_now`
    - `synthetic_week_close_at`
  - ensure these fields are deterministic and scenario-readable
- acceptance:
  - dataset report contains enough timing metadata for k6 to generate hot-week writes without using real current time
- verify:
  - inspect generated JSON under `benchmarks/reports/*_artifacts/dataset.json`

### A3 - Allow scenario configs to control the anchor week
- status: `[x]`
- files:
  - `benchmarks/run_scenario.py`
  - `benchmarks/scenarios/*.json`
- tasks:
  - add `dataset.anchor_week_start`
  - pass it through to `prepare_benchmark_dataset`
  - update existing scenarios to explicit dates
- acceptance:
  - scenario execution is fully date-stable and reproducible
- verify:
  - `python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json`

## Milestone B - Benchmark-safe ingest-time control

### B1 - Add benchmark reference-time override plumbing
- status: `[x]`
- files:
  - `DigitMilePanel/digitmileapi/run_ingestion.py`
  - `DigitMilePanel/digitmileapi/views.py`
  - `DigitMilePanel/digitmile/settings.py`
- tasks:
  - add a benchmark-only gate such as `BENCHMARK_TIME_OVERRIDE_ENABLED`
  - accept a request header like `X-Benchmark-Reference-Time`
  - parse it and pass it into `get_recording_window_status_for_run_finish(...)`
  - ignore the header unless benchmark override mode is enabled
- acceptance:
  - synthetic open-week and closed-week ingest behavior can be chosen intentionally
  - production behavior is unchanged by default
- verify:
  - targeted API tests

### B2 - Add tests for open-week and closed-week override behavior
- status: `[x]`
- files:
  - `DigitMilePanel/digitmileapi/tests.py`
- tasks:
  - add open-week ingest acceptance test under synthetic benchmark time
  - add closed-week rejection test under synthetic benchmark time
  - add a test showing override is ignored when benchmark mode is disabled
- acceptance:
  - tests prove the override is both useful and safely gated
- verify:
  - `docker exec "digitmile-backend" python manage.py test digitmileapi.tests`

## Milestone C - Synthetic hot-week k6 payloads

### C1 - Replace real-time ingest timestamps in k6 payloads
- status: `[x]`
- files:
  - `benchmarks/k6/common.js`
- tasks:
  - remove `Date.now()` as the default source of run timestamps for load tests
  - add helpers that derive random run windows inside the synthetic hot-week interval from the dataset report
  - add a helper to attach benchmark reference-time headers
- acceptance:
  - hot-week load tests no longer depend on wall-clock time
- verify:
  - inspect generated requests in k6 logs or temporary debug output

### C2 - Update ingest scripts to use synthetic hot-week windows
- status: `[x]`
- files:
  - `benchmarks/k6/ingest.js`
  - `benchmarks/k6/mixed_weekly_cycle.js`
- tasks:
  - generate payload timestamps from the dataset report hot-week metadata
  - send `X-Benchmark-Reference-Time` for ingest requests
  - split checks so accepted hot-week ingest is measured separately from intentional rejection scenarios
- acceptance:
  - open-week heavy write scenarios mostly return `200`/`201`
  - closed-week scenarios explicitly expect `409`
- verify:
  - run a small scenario and inspect `ingest_summary.json`

## Milestone D - Actual mixed concurrent load

### D1 - Replace sleep-based low-pressure loops in heavy scenarios
- status: `[x]`
- files:
  - `benchmarks/k6/ingest.js`
  - `benchmarks/k6/teacher_dashboard.js`
  - `benchmarks/k6/replay.js`
  - `benchmarks/k6/mixed_weekly_cycle.js`
- tasks:
  - introduce k6 executors suitable for pressure testing:
    - `constant-arrival-rate`
    - `ramping-arrival-rate`
  - reduce or remove fixed `sleep(1)` behavior in stress scenarios
  - keep small smoke scenarios simple if useful
- acceptance:
  - scenarios can create sustained pressure instead of capped loop throughput
- verify:
  - k6 summary shows materially higher request rates than the current smoke scenarios

### D2 - Run multiple traffic classes concurrently in one k6 execution
- status: `[x]`
- files:
  - `benchmarks/k6/mixed_weekly_cycle.js`
  - optionally new scripts under `benchmarks/k6/`
- tasks:
  - add concurrent named k6 scenarios for:
    - ingest writers
    - dashboard page readers
    - analytics JSON readers
    - turn-insights readers
    - replay readers
  - tag requests by traffic class and endpoint type
- acceptance:
  - one run produces overlapping read/write load instead of sequential script execution
- verify:
  - k6 output shows multiple active scenario groups in one run

## Milestone E - Runtime saturation reporting

### E1 - Sample Docker stats during the benchmark window
- status: `[x]`
- files:
  - `benchmarks/run_scenario.py`
- tasks:
  - add interval sampling during traffic execution
  - collect repeated samples for:
    - `digitmile-backend`
    - `digitmile-postgres`
  - store raw samples and summarized peaks/averages in the final report
- acceptance:
  - reports show whether the run actually stressed CPU and memory, not just whether requests completed
- verify:
  - inspect scenario report for a `resource_summary` or equivalent section with multiple samples

### E2 - Optionally add DB activity sampling
- status: `[ ]`
- files:
  - `benchmarks/run_scenario.py`
- tasks:
  - sample PostgreSQL metadata during the run when feasible
  - candidate sources:
    - `pg_stat_activity`
    - `pg_stat_database`
    - relation sizes
- acceptance:
  - report offers a clearer picture of DB pressure, not just container CPU snapshots
- verify:
  - inspect generated report fields

## Milestone F - Heavy scenario library

### F1 - Add a real hot-week heavy mixed scenario
- status: `[x]`
- files:
  - `benchmarks/scenarios/hot_week_read_write_heavy.json`
- tasks:
  - define a much larger hot-week dataset
  - set explicit synthetic anchor week
  - configure high write pressure and high read pressure concurrently
- acceptance:
  - backend and DB utilization rise meaningfully during the run
- verify:
  - scenario report shows clear resource pressure and stable endpoint behavior

### F2 - Add dashboard-under-ingest-pressure scenario
- status: `[ ]`
- files:
  - `benchmarks/scenarios/dashboard_under_ingest_pressure.json`
- tasks:
  - bias traffic toward teacher reads with meaningful concurrent ingest
- acceptance:
  - report makes it easy to see whether dashboards degrade under active gameplay load

### F3 - Add closed-week rejection-storm scenario
- status: `[ ]`
- files:
  - `benchmarks/scenarios/closed_week_rejection_storm.json`
- tasks:
  - use synthetic benchmark time to intentionally force closed-week behavior
  - configure ingest-heavy traffic and validate stable rejection handling
- acceptance:
  - report clearly distinguishes expected `409` rejection behavior from actual failures

## Milestone G - Report semantics

### G1 - Enrich final scenario report structure
- status: `[ ]`
- files:
  - `benchmarks/run_scenario.py`
- tasks:
  - add explicit sections for:
    - `scenario_summary`
    - `traffic_summary`
    - `latency_by_endpoint_group`
    - `error_summary`
    - `resource_summary`
    - `verification_summary`
  - stop relying on sparse `highlights` extraction that drops useful data
- acceptance:
  - final reports are directly interpretable without opening every artifact file manually

### G2 - Distinguish expected business responses from failures
- status: `[ ]`
- files:
  - `benchmarks/run_scenario.py`
  - `benchmarks/k6/*.js`
  - `benchmarks/README.md`
- tasks:
  - report accepted-write metrics separately from intentional-rejection metrics
  - explain why default k6 `http_req_failed` can disagree with business-level checks
- acceptance:
  - operators can read reports without misinterpreting `409` behavior as system failure

## Milestone H - Docs and operator guidance

### H1 - Update benchmark docs for the new model
- status: `[ ]`
- files:
  - `benchmarks/README.md`
  - `docs/guides/rollup-runbook.md`
  - `docs/decisions/hot-week-load-testing-plan.md`
- tasks:
  - document synthetic benchmark time
  - document open-week vs closed-week load scenarios
  - document how to interpret hot-week stress reports
- acceptance:
  - an engineer can run and interpret the new heavy scenarios from docs alone

### H2 - Add changed-files and manual test guidance to the runbook
- status: `[ ]`
- files:
  - `docs/guides/rollup-runbook.md`
- tasks:
  - extend the benchmark section with the new hot-week load-testing path
  - list which files changed for the new load-testing phase
  - document expected behavior for open-week heavy load and rejection-storm scenarios
- acceptance:
  - manual validation is possible without diff spelunking

## Suggested execution slices

### Slice 1 - Minimum real hot-week stress capability
- A1
- A2
- A3
- B1
- B2
- C1
- C2
- D1
- D2
- E1
- F1

### Slice 2 - Better diagnostics and interpretation
- E2
- G1
- G2
- H1
- H2

### Slice 3 - Extended scenario library
- F2
- F3

## Exit criteria for the whole effort

- at least one scenario generates accepted hot-week writes under concurrent heavy read load,
- at least one scenario intentionally tests closed-week rejection under load,
- reports include enough runtime resource data to confirm actual backend and DB pressure,
- docs explain how to run and interpret the scenarios,
- results no longer depend on the machine's current date.
