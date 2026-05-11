# Thesis Benchmark Plan — Coverage, NFRs, and Outstanding Work

**Status:** In progress (2026-05-11). The toggle harness and four single-optimization comparisons are wired and validated locally. This document tracks the strategic gaps that remain before the thesis evaluation chapter can be considered complete.

## 1. What's already built

| Capability | Where | Status |
|---|---|---|
| Compose overlay system (Tier 2) | `benchmarks/overlays/{no-pgbouncer,pg-defaults,dummy-cache,no-flusher}.yml` | ✅ Working |
| Baseline image builds from git refs (Tier 3) | `benchmarks/run_scenario.py::_build_baseline_image` | ✅ Working locally |
| Baseline tags | `baseline/pre-rollup-analytics`, `baseline/pre-ninja`, `baseline/pre-write-buffer` | ✅ Created |
| Image verification (fails on mismatch) | `verify_backend_image()` in `run_scenario.py` | ✅ Working |
| Live overlay-effect verification (PG settings, env, cache backend, flusher image) | `verify_stack_state()` in `run_scenario.py` | ✅ Working |
| Per-optimization before/after scenarios | `benchmarks/scenarios/before_*.json` × 4 | ✅ Wired |
| Comparison helper | `benchmarks/compare_reports.py` | ✅ Wired |
| Baseline smoke scenario | `benchmarks/scenarios/baseline_smoke_pre_write_buffer.json` | ✅ Validated for F (pre-write-buffer) |

The six "big" optimizations from the audit map to comparisons as follows:

| # | Optimization | How it's compared | Validated? |
|---|---|---|---|
| A | PgBouncer + Django pool settings | `no-pgbouncer.yml` overlay | ✅ Local + server |
| B | PostgreSQL `synchronous_commit=off` + tuning | `pg-defaults.yml` overlay | ✅ Local + server |
| C | Rollup-only analytics (hot data removed from reads) | `baseline/pre-rollup-analytics` git tag (image) | ⚠ Not yet validated end-to-end |
| D | Django query cache + invalidation | `dummy-cache.yml` overlay | ✅ Local + server (needed two prod-safe code fixes for DummyCache compatibility) |
| E | django-ninja + Pydantic v2 (Rust) ingest | `baseline/pre-ninja` git tag (image) | ⚠ Not yet validated; expected to need endpoint URL fix in k6 |
| F | Redis-buffered ingest + flusher service | `baseline/pre-write-buffer` git tag + `no-flusher.yml` overlay | ✅ Local; ⚠ Server requires registry-based image distribution (see §5) |

## 2. Non-Functional Requirements (proposed)

NFRs derive directly from `docs/research/ingest-capacity-model.md` so each requirement is defensible against the canonical capacity model rather than invented for the thesis. Numbers below correspond to the **medium adoption (50%)** scenario unless noted, on the production target hardware (2 vCPU / 4 GB).

| ID | Requirement | Capacity-model source |
|---|---|---|
| **NFR-1** | Sustain **11 ingest RPS for 15 min** with p95 < 1000 ms, ≤ 0.5% dropped iterations, backend CPU avg < 90% | §7 steady-state, medium |
| **NFR-2** | Absorb a **60 s burst of 29 RPS** with zero 5xx, p95 < 2000 ms, and Redis `ingest_buffer` drains to 0 within 30 s of burst end | §5 lesson-bell, medium |
| **NFR-3** | **Dashboard p95 < 3000 ms** during NFR-1 traffic (teachers reading during class) | Realistic mixed regime |
| **NFR-4** | **Friday compaction** completes within 60 s for one teacher's week with no dropped k6 iterations on a concurrent 1 req/s mixed read load | Operational |
| **NFR-5** | **After a deliberate 5-min overload at 2× capacity** (22 RPS), the system returns to NFR-1 baseline p95 within 2 min once load drops to 11 RPS | Resilience |

For high adoption (75%) the same NFRs scale to 16 RPS steady / 44 RPS burst — captured by re-running the same scenarios with bumped rates rather than authoring new NFRs.

Each NFR maps to **one scenario** and produces **one pass/fail line** in the thesis. That's the structure committees grade well.

## 3. Coverage matrix

| Question the thesis needs to answer | Scenarios today | Gap |
|---|---|---|
| Does each optimization help? | `before_*` × 4 + reference scenarios | ✅ Covered |
| Where's the throughput ceiling? | `ingest_isolation`, `stress_ramp` | ✅ Covered |
| Does it handle the burst regime? | `lesson_bell` | ✅ Covered |
| Does it sustain target load over **time**? | — | ❌ **No endurance test** |
| Does it recover from overload? | — | ❌ Missing (NFR-5) |
| What's the combined effect of **all opts stacked**? | — | ❌ Missing |
| Does it meet declared NFRs (pass/fail)? | — | ❌ Missing (NFRs 1–5) |
| How does it scale with **data volume**? | partial via `mixed_semester_*` | ⚠ Indirect |
| Cold-cache vs warm-cache effect on dashboards? | — | ❌ Missing — relevant for D |
| Does compaction degrade reads? | `compaction_under_read_load` | ✅ Covered |

The three gaps that most hurt thesis credibility are **endurance**, **NFR pass/fail**, and **stacked-optimization measurement**. Without them, the claim "the system works" rests on 4-minute peak-load runs — a defense committee will reasonably ask "what about 30 minutes" and "what does the *combination* of these optimizations buy."

## 4. Scenarios to add

Four scenarios close all five NFRs and the cumulative-effect question. Naming follows the existing convention (snake_case under `benchmarks/scenarios/`).

### 4.1 `endurance_steady.json` — closes NFR-1

- 11 ingest RPS sustained for 15 minutes (no ramp)
- Dataset: `national_medium` scale (~1,000 students, 2 hot weeks)
- Watch metrics: `LLEN ingest_buffer` over time (should stay near zero), backend memory (no creep), p95 latency (no walk-up)
- Pass: zero drops, p95 < 1000 ms across the full window, CPU avg < 90%

### 4.2 `overload_recovery.json` — closes NFR-5

- Three phases via `ramping-arrival-rate`: 2 min ramp 0→22 RPS, 5 min hold at 22 RPS (deliberate overload at 2× capacity), 5 min recovery at 11 RPS
- Dataset: same as 4.1
- Watch metrics: when the third phase begins, how many seconds until p95 returns to < 1000 ms; how many seconds until `ingest_buffer` drains
- Pass: full recovery to NFR-1 baseline within 2 min of load drop

### 4.3 `mixed_steady.json` — closes NFR-3 and NFR-4

- 11 ingest RPS + 4 read classes at 1 req/s each (dashboard, analytics, turn_insights, replay) for 10 minutes
- Optional Friday-compaction trigger mid-run (via `verification.compact_after_traffic_week_index`)
- Dataset: `national_medium` scale
- Pass: dashboard p95 < 3000 ms, analytics p95 < 5000 ms, compaction (when triggered) < 60 s with no read drops during the compaction window

### 4.4 `before_all_optimizations.json` — the headline thesis chart

- `benchmark_image_ref: baseline/pre-write-buffer` **+** `compose_overlays: ["no-pgbouncer.yml", "pg-defaults.yml", "dummy-cache.yml", "no-flusher.yml"]`
- Paired with current-tree `national_medium.json`
- This produces the single most impactful comparison in the thesis: **"all optimizations on" vs "all optimizations off" on identical hardware**. The cumulative delta will be much more dramatic than any individual A/B/D/F comparison.
- Caveat: this paths against the F baseline image (pre-write-buffer) which is also pre-everything-after-F. Stacking overlays on top reverts A, B, D as well. Verify the resulting stack_state in the report confirms all flips took effect.

## 5. Outstanding issues

### 5.1 Server has no git → baseline image builds fail

The thesis-server deploy is not a git checkout (`fatal: not a git repository (or any of the parent directories): .git`). The current `_apply_baseline_image_ref` requires `git rev-parse` to resolve the ref to a SHA before building, which fails on the server.

**Resolution plan (tracked separately, partial fix applied):**

Add a `benchmark_image` field to the scenario JSON that, when set, bypasses git entirely and uses the named Docker image directly. Workflow becomes:

1. Build baseline images locally where git is available (one-time per baseline).
2. Tag for a registry (`docker tag digitmile-benchmark-backend:baseline-… gashmurble/digitmile-baseline:pre-write-buffer`) and push.
3. On the server, scenario JSON sets `benchmark_image: "gashmurble/digitmile-baseline:pre-write-buffer"` (compose pulls automatically if missing locally).

Implementation goes in `_apply_baseline_image_ref`: if `benchmark_image` is present, use it; if `benchmark_image_ref` is present and git is available, build from git; if `benchmark_image_ref` is set but git is unavailable, fail with a clear "set `benchmark_image` on hosts without git" message.

### 5.2 C and E baselines unvalidated

Both `baseline/pre-rollup-analytics` and `baseline/pre-ninja` git tags exist but no smoke scenario has been written or run against them. Expected friction:

- **E (pre-ninja, commit `9bb4925`)**: ingest URL was `/panel/insertRunData/` (or similar), not `/panel/api/runs/ingest/`. The k6 scripts hit the new URL and will get 404. Fix: either author a baseline-specific k6 script, or have the scenario JSON pass an endpoint override env var.
- **C (pre-rollup-analytics, commit `2f0a317`)**: oldest baseline. `prepare_benchmark_dataset` CLI may differ; analytics endpoints may differ; rollup tables likely don't exist yet. Significant work to validate.

Both are deferable — A, B, D, F + the four new scenarios (§4) already cover the strongest thesis claims. C and E nice-to-have for completeness.

### 5.3 Cold-cache vs warm-cache methodology

Not a scenario; a **two-run protocol** on the existing `realistic_school_day` scenario:

1. Run scenario, save report A.
2. Re-run scenario immediately, save report B.
3. Run A's dashboard p95 is cold-cache cost; run B's is warm-cache. The delta is the cache hit rate's value.

For the `before_query_cache_realistic_school_day` (D-reverted) scenario, both runs will look like A (no caching). Comparing the four-cell table (D-on cold, D-on warm, D-off cold, D-off warm) shows what the cache contributes vs the warmth alone.

## 6. Methodology guardrails

To keep before/after comparisons honest:

1. **Same machine for paired runs.** Local-vs-server hardware differs; never mix. The thesis chapter records which host each run came from.
2. **Same dataset.** All `before_*.json` scenarios copy the `dataset:` block verbatim from their reference scenario. Verified by diffing `dataset_report.weeks` in the two reports.
3. **Same script.** Re-using `mixed_weekly_cycle.js` for ingest-only scenarios is deliberate — re-using is the safer choice. Diverging scripts would muddy the delta.
4. **Image verification.** `scenario_summary.image_info` in every report independently proves which image (and which commit) produced the numbers. Cross-check before drawing conclusions.
5. **Stack state verification.** `scenario_summary.stack_state` in every report shows the actual PG settings, env vars, cache backend, and flusher image that ran. Confirms the overlay actually changed runtime state.

## 7. Next steps in order

1. **Fix the server git issue** — add `benchmark_image` field, document push/pull workflow (§5.1).
2. **Write the four §4 scenarios.**
3. **Run all four on local + server**, capture reports.
4. **Generate comparison tables** via `compare_reports.py` for each pair.
5. **Write the thesis evaluation chapter** using §2 NFRs as the structural skeleton: one section per NFR, pass/fail verdict, headline number, link to the report.
6. (Optional) Validate C and E baselines if time permits.

## 8. References

- `docs/research/ingest-capacity-model.md` — the canonical capacity model that NFRs derive from
- `docs/decisions/write-buffering-adr.md` — F (the headline architectural change)
- `OPTIMIZATION_AUDIT.md` — proposed R1–R16 (not in scope for this thesis but cited as future work)
- `benchmarks/README.md` — operational guide for running scenarios
- `benchmarks/overlays/README.md` — overlay catalogue
