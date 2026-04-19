# Hot-Week Load Testing Implementation Plan

Last updated: 2026-04-19 (status note added); original plan: 2026-03-15.

> **Status as of 2026-04-19:** Slice 1 (Milestones A1–A3, B1–B2, C1–C2, D1–D2, E1, F1) has **landed**. The synthetic benchmark clock, `BENCHMARK_TIME_OVERRIDE_ENABLED` gate, `X-Benchmark-Reference-Time` header, `prepare_benchmark_dataset --anchor-week-start`, constant-arrival-rate k6 executors, Docker-stats sampling in `run_scenario.py`, and the `hot_week_read_write_heavy.json` scenario all exist. See `docs/decisions/hot-week-load-testing-checklist.md` for the ticked checkboxes. The "Current limitations" section below describes the **pre-Slice-1** state and is retained as historical context; Slice 2 (diagnostics/interpretation) and Slice 3 (extended scenarios) are still open.

## Purpose

This document is the implementation plan for turning the current benchmark tooling into a real hot-week load-testing system that can stress the backend and database with concurrent reads and writes under a reproducible synthetic school-week timeline.

It is written as an execution guide for agents and engineers who will implement the next benchmark phase.

## Context for fresh agents

If you were not part of the earlier implementation work, read these files before making changes.

### Read first

- `docs/decisions/next-phase-log.md`
  - establishes what phases are already done versus what remains.
- `docs/guides/rollup-runbook.md`
  - shows the currently implemented operator workflow, benchmark path, and per-phase changed-file map.
- `benchmarks/README.md`
  - explains how benchmark traffic currently runs, especially the Docker-network path used by k6.

### Then inspect the current benchmark implementation

- `benchmarks/run_scenario.py`
  - current scenario orchestration, Docker-network k6 invocation, report assembly, and runtime sampling limitations.
- `benchmarks/scenarios/*.json`
  - current dataset shape and traffic configuration surface.
- `benchmarks/k6/common.js`
  - shared helpers, current request headers, and current timestamp generation assumptions.
- `benchmarks/k6/ingest.js`
- `benchmarks/k6/teacher_dashboard.js`
- `benchmarks/k6/replay.js`
- `benchmarks/k6/mixed_weekly_cycle.js`
  - current k6 workload behavior; inspect these before assuming traffic is truly concurrent or arrival-rate based.

### Inspect the backend files that control benchmark semantics

- `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
  - current seeded data generation, hot-week layout, and report contents.
- `DigitMilePanel/digitmileapi/run_ingestion.py`
  - canonical ingest logic and recording-window enforcement path.
- `DigitMilePanel/digitmileapi/views.py`
  - request handling path for `/panel/api/runs/ingest/`.
- `DigitMilePanel/digitmileapi/tests.py`
  - current tests that protect ingest behavior and benchmark tooling.

### Crucial context to understand before editing

- canonical Unity-compatible ingest on `/panel/api/runs/ingest/` already exists; this document is about benchmark realism, not redoing ingest.
- closed-week ingest rejection already exists; the missing piece is a benchmark-safe way to evaluate open/closed behavior against a synthetic reference time.
- the current benchmark path is Docker-first: k6 runs in its own container on the backend Docker network, targets `http://digitmile-backend:8000`, and sends `Host: localhost`.
- `hot_only_small` is currently a smoke scenario, not a true hot-week stress test.
- current benchmark correctness is still partially tied to real wall-clock time because dataset prep and k6 payload timestamps are not yet fully synthetic.
- report interpretation is tricky today because expected business rejections such as `409` can be mixed with real transport or application failures.
- production behavior must stay unchanged unless a benchmark-only override is explicitly enabled.

## Goal

Build a reproducible load-testing pipeline that can answer questions like:

- What happens when a hot week is actively receiving many gameplay writes and many teacher reads at the same time?
- Do `/panel/api/runs/ingest/`, dashboard reads, visualization reads, and replay reads remain correct under load?
- What CPU, memory, DB, and latency profiles do we see under that pressure?
- Can we compare backend+DB-only benchmarks against optional full-path reverse-proxy benchmarks later?

## Recommended benchmark target

Primary target for this phase:

- benchmark `backend + db` directly

Reason:

- it gives cleaner application and database bottleneck data,
- it avoids proxy/static noise during early load-shape tuning,
- it is easier to reason about request success and latency under high write pressure.

Optional later extension:

- add a second benchmark lane that targets the full exposed stack through nginx once the backend+db lane is stable.

## Current limitations to fix

The current benchmark pipeline is useful for smoke checks, but it is not yet a true hot-week stress test.

### Current gaps

- dataset generation anchors weeks to real `timezone.now()` instead of a synthetic benchmark clock,
- k6 ingest payloads use `Date.now()` instead of timestamps from a controlled hot week,
- ingest policy still evaluates the real current time unless the code is patched or overridden,
- k6 scripts currently use low-pressure `vus + sleep(1)` loops,
- scenario scripts run one after another rather than as a concurrent mixed workload,
- resource reporting is mostly before/after snapshots rather than during-run pressure sampling,
- current reports do not clearly separate successful ingest throughput from business rejections caused by closed-week policy.

## Design principles

- benchmark time must be synthetic and reproducible,
- hot-week ingest must succeed during load unless a scenario explicitly tests closed-week rejection,
- concurrency must be generated in one mixed run, not inferred from separate sequential runs,
- scenario configuration should control load shape without editing script source,
- reports must distinguish functional failures from expected business responses,
- backend and DB saturation signals must be collected during the run, not only before and after it,
- keep the primary benchmark lane focused on backend+db first.

## Implementation order

1. Introduce a synthetic benchmark clock.
2. Make ingest policy evaluable against benchmark time.
3. Make dataset generation anchor hot/cold weeks to that synthetic timeline.
4. Make k6 ingest payloads use synthetic hot-week timestamps.
5. Replace low-pressure loops with concurrent arrival-rate-based mixed scenarios.
6. Add runtime CPU/memory/DB sampling during the benchmark window.
7. Add heavy hot-week scenario configs.
8. Add validation tests and operator documentation.
9. Optionally add a full reverse-proxy benchmark lane later.

## Phase 1 - Synthetic benchmark clock

### Objective

Decouple benchmark data generation and benchmark traffic from real wall-clock time.

### Target files

- `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
- `benchmarks/run_scenario.py`
- `benchmarks/scenarios/*.json`

### Required changes

- add an `--anchor-week-start` option to dataset preparation,
- derive all generated weeks from that fixed anchor instead of `timezone.now()`,
- emit these fields in the dataset report:
  - `anchor_week_start`
  - `hot_week_start`
  - `hot_week_end`
  - `synthetic_now`
  - `synthetic_week_close_at`
- allow scenario config to define the benchmark anchor week explicitly.

### Acceptance criteria

- rerunning the same scenario with the same seed and anchor week produces the same week layout,
- the report explicitly identifies which week is considered hot,
- no benchmark scenario depends on the machine's current date for semantic correctness.

## Phase 2 - Ingest policy override for benchmark time

### Objective

Allow load tests to exercise open-week and closed-week behavior intentionally rather than accidentally.

### Target files

- `DigitMilePanel/digitmileapi/run_ingestion.py`
- `DigitMilePanel/digitmileapi/views.py`
- `DigitMilePanel/digitmile/settings.py`
- `DigitMilePanel/digitmileapi/tests.py`

### Required changes

- add a safe benchmark-only reference-time override path for ingest policy evaluation,
- recommended implementation:
  - read an optional header such as `X-Benchmark-Reference-Time` or a benchmark-only setting/flag,
  - use it only when benchmark mode is explicitly enabled,
  - parse it into an aware datetime and pass it into `get_recording_window_status_for_run_finish(...)`,
- preserve current production behavior when the override is absent,
- add tests for:
  - synthetic open-week ingest,
  - synthetic closed-week ingest,
  - override disabled in normal production mode.

### Acceptance criteria

- benchmark traffic can intentionally force open-week acceptance for synthetic hot-week writes,
- closed-week behavior remains testable,
- no production request behavior changes unless benchmark mode is explicitly enabled.

## Phase 3 - Dataset generation aligned to hot-week load

### Objective

Make the seeded dataset represent a meaningful semester with a clear hot tail and optional compacted cold history.

### Target files

- `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py`
- `DigitMilePanel/digitmileapi/tests.py`

### Required changes

- add scenario-controlled dataset anchor fields into the report,
- ensure generated hot weeks are still open relative to the synthetic benchmark clock,
- optionally emit richer target groups in the dataset report:
  - `ingest_targets_hot_week`
  - `teacher_targets`
  - `dashboard_filter_targets`
  - `replay_targets_hot`
  - `replay_targets_cold`
- add an option to bias more runs into the hot week if the scenario wants high write density,
- keep dataset prep reproducible by seed.

### Acceptance criteria

- the dataset report provides enough information for k6 to generate realistic hot-week requests without inventing timestamps on the fly,
- hot/cold replay targets are explicitly available when mixed replay load is needed.

## Phase 4 - Synthetic-time k6 payload generation

### Objective

Make ingest load target the synthetic hot week rather than real current time.

### Target files

- `benchmarks/k6/common.js`
- `benchmarks/k6/ingest.js`
- `benchmarks/k6/mixed_weekly_cycle.js`
- `benchmarks/k6/retry_storm_ingest.js` or equivalent if added

### Required changes

- replace `Date.now()` payload timing with timestamps derived from dataset report fields,
- generate random run windows inside the synthetic hot-week interval,
- send the benchmark reference-time override header for ingest requests,
- add helper functions such as:
  - `pickSyntheticRunWindow(...)`
  - `buildUnityPayloadForSyntheticHotWeek(...)`
  - `benchmarkHeaders(...)`
- separate success checks for:
  - accepted ingest (`200`/`201` expected for open-week load),
  - intentionally rejected ingest (`409` expected only in closed-week scenarios).

### Acceptance criteria

- heavy ingest scenarios mostly return accepted responses when configured as open-week scenarios,
- closed-week scenarios can still intentionally assert rejection behavior.

## Phase 5 - Real concurrent mixed load

### Objective

Simulate actual hot-week contention with concurrent writers and readers.

### Target files

- `benchmarks/k6/mixed_weekly_cycle.js`
- optionally split into:
  - `benchmarks/k6/hot_week_read_write_heavy.js`
  - `benchmarks/k6/dashboard_under_ingest_pressure.js`
  - `benchmarks/k6/compaction_under_load.js`

### Required changes

- move away from simple `vus + sleep(1)` loops for heavy scenarios,
- use k6 executors such as:
  - `constant-arrival-rate`
  - `ramping-arrival-rate`
  - optional `per-vu-iterations` for deterministic warmup/setup flows,
- define concurrent named scenarios in one script/run for:
  - ingest writers,
  - dashboard page readers,
  - analytics JSON readers,
  - turn-insights readers,
  - replay readers,
- tag requests by traffic class so results can be split by endpoint type.

### Acceptance criteria

- one benchmark run can generate overlapping read/write pressure,
- endpoint classes can be interpreted separately from one summary output,
- high-utilization scenarios no longer depend on sleep-based low-throughput loops.

## Phase 6 - Runtime saturation metrics

### Objective

Capture whether the benchmark actually stressed backend and database resources.

### Target files

- `benchmarks/run_scenario.py`
- optional new helper module under `benchmarks/`

### Required changes

- sample `docker stats` repeatedly during the benchmark window rather than only before/after,
- recommended sample interval: every 2 to 5 seconds,
- collect per-sample metrics for:
  - backend CPU
  - backend memory
  - DB CPU
  - DB memory
- optionally collect DB-level stats snapshots using `docker exec digitmile-postgres psql ...` for:
  - `pg_stat_activity`
  - `pg_stat_database`
  - relation sizes
- summarize runtime stats in the final report with:
  - avg
  - peak
  - sample count
  - timestamped samples.

### Acceptance criteria

- reports show whether the run actually caused meaningful CPU/DB pressure,
- backend and DB saturation can be compared across scenarios.

## Phase 7 - Heavy hot-week scenarios

### Objective

Add scenarios that are clearly intended for real stress testing, not just smoke validation.

### Recommended new scenario files

- `benchmarks/scenarios/hot_week_read_write_heavy.json`
- `benchmarks/scenarios/dashboard_under_ingest_pressure.json`
- `benchmarks/scenarios/replay_plus_analytics_hot_tail.json`
- `benchmarks/scenarios/closed_week_rejection_storm.json`

### Recommended scenario characteristics

#### `hot_week_read_write_heavy.json`

- dataset:
  - 6 to 12 teachers
  - 3 to 5 classrooms per teacher
  - 20 to 30 students per classroom
  - 10 to 12 weeks total
  - 2 hot weeks
  - older weeks compacted
- traffic:
  - high ingest arrival rate
  - high dashboard/analytics read rate
  - moderate replay traffic
- goal:
  - stress backend and DB with mixed hot writes and historical reads

#### `dashboard_under_ingest_pressure.json`

- dataset biased toward many students per teacher
- very high teacher-read rate plus moderate ingest
- goal:
  - identify whether teacher statistics endpoints degrade under simultaneous gameplay traffic

#### `replay_plus_analytics_hot_tail.json`

- mix hot and cold replay traffic with analytics reads
- goal:
  - evaluate replay correctness and latency while history contains compacted and uncompacted data

#### `closed_week_rejection_storm.json`

- synthetic closed-week reference time
- goal:
  - measure rejection path stability and idempotent retry behavior under storm conditions

### Acceptance criteria

- at least one scenario produces clearly elevated backend and DB load,
- at least one scenario specifically validates accepted hot-week writes,
- at least one scenario validates intentional closed-week rejection under load.

## Phase 8 - Report semantics and interpretation

### Objective

Make reports easier to interpret so operators know what they are looking at.

### Target files

- `benchmarks/run_scenario.py`
- `benchmarks/README.md`
- `docs/guides/rollup-runbook.md`

### Required changes

- enrich the final report with explicit sections such as:
  - `scenario_summary`
  - `dataset_summary`
  - `traffic_summary`
  - `latency_by_endpoint_group`
  - `error_summary`
  - `resource_summary`
  - `verification_summary`
- distinguish clearly between:
  - expected business rejections,
  - transport/application failures,
  - k6 check failures,
  - k6 default `http_req_failed` semantics,
- document how to interpret accepted ingest vs rejected ingest scenarios.

### Acceptance criteria

- someone reading the JSON report can tell whether a run represents successful hot-week write load, rejection-path load, or historical-read load,
- reports no longer require artifact-by-artifact guesswork.

## Phase 9 - Optional full-stack proxy lane

### Objective

Add an optional second benchmark mode for end-to-end path testing through nginx.

### Target files

- `benchmarks/run_scenario.py`
- `benchmarks/scenarios/*.json`
- `benchmarks/README.md`

### Required changes

- allow scenario config to specify benchmark path mode:
  - `backend_direct`
  - `proxy_full_path`
- when `proxy_full_path` is selected, target the appropriate proxy URL and request host header,
- keep backend-direct as the default and recommended mode.

### Acceptance criteria

- backend+db and full-path results can be compared intentionally,
- proxy overhead does not contaminate the primary backend bottleneck analysis by default.

## Test plan

### Automated tests to add/update

- dataset-prep tests for fixed anchor week output,
- ingest policy tests for benchmark reference-time override,
- k6 helper unit-like smoke validation where practical for dataset-driven timestamp generation,
- runner tests for report schema assembly where practical,
- scenario smoke tests that verify generated reports contain the expected top-level fields.

### Manual validation

- run a small open-week synthetic scenario and confirm ingest returns mostly `200/201`,
- run a closed-week rejection scenario and confirm ingest returns `409` by design,
- run a heavy mixed scenario and confirm:
  - backend CPU rises meaningfully,
  - DB CPU rises meaningfully,
  - dashboard and analytics checks still pass,
  - compaction/verification still succeed when included.

## Proposed deliverables checklist

- [ ] synthetic benchmark clock support
- [ ] benchmark ingest-time override
- [ ] dataset report with explicit hot-week metadata
- [ ] k6 payloads using synthetic hot-week timestamps
- [ ] concurrent arrival-rate-based mixed scenarios
- [ ] runtime CPU/memory/DB sampling during benchmark
- [ ] heavy hot-week scenario configs
- [ ] enriched final report schema
- [ ] documentation updates for interpretation and operation

## Recommended first implementation slice

If this work needs to be split into safe chunks, start here:

1. synthetic benchmark clock in dataset prep,
2. benchmark-only ingest reference-time override,
3. k6 ingest payloads driven by synthetic hot-week timestamps,
4. one new heavy mixed scenario using concurrent arrival-rate execution,
5. runtime `docker stats` sampling during the run.

That slice gives the first genuinely useful hot-week stress benchmark without requiring every report/documentation enhancement up front.
