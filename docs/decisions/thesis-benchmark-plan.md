# Thesis Benchmark Plan — Coverage, NFRs, Methodology, and Outstanding Work

**Status:** In progress (2026-05-11, last updated after first server runs). Toggle harness wired end-to-end on both local and the deployment server. Four single-optimization marginal comparisons (A, B, D, F) have been run on the production-target hardware (2 vCPU / 4 GB). The pending work is: (1) re-evaluate the existing comparisons under the marginal-vs-standalone framing in §3, (2) author the four scenarios in §6 that close the remaining NFR coverage and produce the headline cumulative chart.

## 1. What's already built

| Capability | Where | Status |
|---|---|---|
| Compose overlay system (Tier 2) | `benchmarks/overlays/{no-pgbouncer,pg-defaults,dummy-cache,no-flusher}.yml` | ✅ Working |
| Baseline image builds from git refs (Tier 3, local) | `benchmarks/run_scenario.py::_build_baseline_image` | ✅ Working |
| Explicit `benchmark_image` field for git-less hosts | `benchmarks/run_scenario.py::_apply_baseline_image_ref` + `ensure_backend_image()` pull-on-miss | ✅ Working on the server |
| Baseline tags | `baseline/pre-rollup-analytics`, `baseline/pre-ninja`, `baseline/pre-write-buffer` | ✅ Created |
| Baseline image distribution | `gashmurble/digitmile-baseline:pre-write-buffer` pushed to Docker Hub | ✅ For F; C and E pending |
| Image verification (fails on mismatch) | `verify_backend_image()` | ✅ |
| Live overlay-effect verification | `verify_stack_state()` (PG settings, env, cache backend, flusher image) | ✅ |
| Per-optimization before/after scenarios | `benchmarks/scenarios/before_*.json` × 4 | ✅ Wired |
| Comparison helper | `benchmarks/compare_reports.py` | ✅ |
| Baseline smoke scenario | `benchmarks/scenarios/baseline_smoke_pre_write_buffer.json` | ✅ Validated for F |
| Production-safe DummyCache fixes | `settings.py::REDIS_URL` top-level + `delete_pattern` feature-detect in compaction commands | ✅ Shipped |

The six "big" optimizations from the audit map to comparisons as follows:

| # | Optimization | How it's compared | Run on local | Run on server |
|---|---|---|---|---|
| A | PgBouncer + Django pool settings | `no-pgbouncer.yml` overlay | ✅ | ✅ |
| B | PostgreSQL `synchronous_commit=off` + tuning | `pg-defaults.yml` overlay | ✅ | ✅ |
| C | Rollup-only analytics (hot data removed from reads) | `baseline/pre-rollup-analytics` git tag | ⚠ Unvalidated | ⚠ Image not pushed |
| D | Django query cache + invalidation | `dummy-cache.yml` overlay | ✅ | ✅ |
| E | django-ninja + Pydantic v2 (Rust) ingest | `baseline/pre-ninja` git tag | ⚠ Unvalidated | ⚠ Image not pushed |
| F | Redis-buffered ingest + flusher service | `baseline/pre-write-buffer` + `no-flusher.yml` | ✅ | ✅ |

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

## 3. Methodology — marginal effects vs standalone effects

**This is the most important conceptual distinction in the evaluation chapter.** It must be stated explicitly before any result tables.

The four `before_X` scenarios each revert **only optimization X** while leaving everything else on. So each measurement compares:

| Scenario | A | B | D | F |
|---|---|---|---|---|
| `before_pgbouncer_*` | **off** | on | on | on |
| `before_pg_tuning_*` | on | **off** | on | on |
| `before_query_cache_*` | on | on | **off** | on |
| `before_write_buffer_*` | on | on | on | **off** |
| `ingest_isolation` / `realistic_school_day` (reference) | on | on | on | on |

This measures the **marginal contribution** of each optimization *given everything else is already on*. It answers:

> "Should we keep optimization X in the current production stack today?"

It does **not** answer:

> "How much did optimization X help when it was first introduced, before the others existed?"

That's the **standalone contribution**, which has a different baseline: all other optimizations *off*, only X toggled. The two answers can disagree, especially when optimizations interact through the workload they create.

**Concrete example from the data:** PgBouncer's marginal contribution in the current stack is negative (Table in §5). The likely cause is optimization F (Redis write buffer): F decoupled the HTTP request path from PostgreSQL, leaving only a single sub-millisecond `Student.exists()` check per request. PgBouncer's per-request handshake (forced by `CONN_MAX_AGE=0`) now exceeds the savings from connection pooling. PgBouncer was likely *standalone-beneficial* when introduced because every request synchronously wrote a Run + ~30 TurnEvent rows; F changed the workload and inverted A's cost-benefit.

This isn't a measurement bug — it's a textbook case of optimization interaction, and it is itself a thesis-worthy finding.

**Reporting requirement in the evaluation chapter:**

1. State explicitly which type of measurement each table reports.
2. The current four `before_*.json` results are **marginal-only**.
3. The `before_all_optimizations.json` scenario (§6.4) produces **cumulative**: all four together vs none.
4. Optional **standalone** measurements (§6.5) require additional scenarios; treat as nice-to-have, not required.

## 4. Coverage matrix

| Question the thesis needs to answer | Scenarios today | Gap |
|---|---|---|
| Does each optimization help marginally? | `before_*` × 4 + reference | ✅ Covered (run; need re-interpretation per §3) |
| Where's the throughput ceiling? | `ingest_isolation`, `stress_ramp` | ✅ Covered |
| Does it handle the burst regime? | `lesson_bell` | ✅ Covered |
| Does it sustain target load over **time**? | — | ❌ **No endurance test (NFR-1)** |
| Does it recover from overload? | — | ❌ Missing (NFR-5) |
| What's the **cumulative** effect of all opts stacked? | — | ❌ Missing (headline chart) |
| Does it meet declared NFRs (pass/fail)? | — | ❌ Missing (NFRs 1–5) |
| How does it scale with **data volume**? | partial via `mixed_semester_*` | ⚠ Indirect |
| Cold-cache vs warm-cache effect on dashboards? | — | ❌ Missing — relevant for D |
| Does compaction degrade reads? | `compaction_under_read_load` | ✅ Covered |
| Standalone (each-vs-bare-baseline) effects | — | ⚠ Optional |

The three gaps that most hurt thesis credibility are **endurance** (NFR-1), **overload recovery** (NFR-5), and the **cumulative stacked comparison** (the single most impactful chart). Without them, the claim "the system works" rests on 4-minute peak-load ramps — a defense committee will reasonably ask "what about 30 minutes" and "what does the *combination* of these optimizations buy."

## 5. Results so far (marginal comparisons, server runs, 2026-05-11)

All four marginal comparisons have been run on the production server. Headline numbers:

| Comparison | Reverted | http_req_duration.avg | p95 | drops | load_health | Reading |
|---|---|---|---|---|---|---|
| **A — PgBouncer** | A off vs A on | 10.66 → 412.88 ms | 23.47 → 1829.56 ms | 0 → 86 | green → yellow | **A hurts marginally** (-40× latency); interaction with F |
| **B — PG tuning** | B off vs B on | 412.49 → 412.88 ms | 2016.82 → 1829.56 ms | 103 → 86 | yellow → yellow | **Near-zero effect**; tuned values mostly match PG 16 defaults |
| **D — Query cache** | D off vs D on | 238.07 → 194.95 ms | 928.97 → 862.90 ms | — → — | green → green | Modest 18% improvement at 5 RPS mixed (scales with concurrency) |
| **F — Write buffer** | F off vs F on | 811.69 → 412.88 ms | 3563.96 → 1829.56 ms | 177 → 86 | yellow → yellow | **Headline win** — ~50% latency reduction, drops halved |

Reports under `benchmarks/sever_reports/reports/comparison_*.md`.

### Interpretive notes (to fold into the thesis chapter)

- **A — PgBouncer (negative marginal contribution).** Frame as an interaction effect under §3. Don't bury it; it's a structured finding about evolving workloads. The original commit (03fae64) was correct under the pre-F workload; F flipped the cost-benefit. A confirming re-run is advisable to rule out single-trial noise, but the internal consistency (same RPS, dataset, image attestation) is strong.
- **B — PG tuning (negligible).** Consistent with the pre-run inspection of `pg_settings` showing that six of eight `-c` flags duplicate PG 16 defaults. Only `synchronous_commit=off` and `random_page_cost=1.1` actually differ, and at this traffic profile they barely move the needle (the writes mostly land in Redis first, so commit semantics affect the flusher, not the HTTP path).
- **D — Query cache (modest at single-teacher load).** 5 RPS / single teacher = limited cache reuse opportunity. The cache's value scales with **concurrent dashboard users hitting overlapping queries** — not measured yet. A follow-up scenario at 10 concurrent teachers would quantify it.
- **F — Write buffer (the headline).** Matches the ADR's prediction. ~50% latency reduction, ~50% fewer drops, ~20% lower backend CPU. This belongs as the headline chart in the evaluation chapter.

### What the "—" cells mean (not bugs)

- `http_req_duration.p(99)` is "—" because k6's default summary export doesn't include p99 — only p95. To get p99 we'd need a `summaryTrendStats` option on the k6 scripts. Defer; p95 is sufficient for the thesis.
- `dropped_iterations.count` is "—" when k6 didn't emit the metric (zero drops). Read as 0; the `load_health: green` independently confirms it.

## 6. Scenarios to add

Four scenarios close all five NFRs and the cumulative-effect question. Naming follows the existing convention (snake_case under `benchmarks/scenarios/`). An optional fifth set covers true standalone measurements.

### 6.1 `endurance_steady.json` — closes NFR-1

- 11 ingest RPS sustained for 15 minutes (no ramp)
- Dataset: `national_medium` scale (~1,000 students, 2 hot weeks)
- Watch metrics: `LLEN ingest_buffer` over time (should stay near zero), backend memory (no creep), p95 latency (no walk-up)
- Pass: zero drops, p95 < 1000 ms across the full window, CPU avg < 90%

### 6.2 `overload_recovery.json` — closes NFR-5

- Three phases via `ramping-arrival-rate`: 2 min ramp 0→22 RPS, 5 min hold at 22 RPS (deliberate overload at 2× capacity), 5 min recovery at 11 RPS
- Dataset: same as 6.1
- Watch metrics: when the third phase begins, how many seconds until p95 returns to < 1000 ms; how many seconds until `ingest_buffer` drains
- Pass: full recovery to NFR-1 baseline within 2 min of load drop

### 6.3 `mixed_steady.json` — closes NFR-3 and NFR-4

- 11 ingest RPS + 4 read classes at 1 req/s each (dashboard, analytics, turn_insights, replay) for 10 minutes
- Optional Friday-compaction trigger mid-run (via `verification.compact_after_traffic_week_index`)
- Dataset: `national_medium` scale
- Pass: dashboard p95 < 3000 ms, analytics p95 < 5000 ms, compaction (when triggered) < 60 s with no read drops during the compaction window

### 6.4 `before_all_optimizations.json` — the headline thesis chart

- `benchmark_image_ref: baseline/pre-write-buffer` **+** `benchmark_image: gashmurble/digitmile-baseline:pre-write-buffer` (for server) **+** `compose_overlays: ["no-pgbouncer.yml", "pg-defaults.yml", "dummy-cache.yml", "no-flusher.yml"]`
- Paired with current-tree `national_medium.json`
- This produces the single most impactful comparison in the thesis: **"all optimizations on" vs "all optimizations off" on identical hardware**.
- Caveat: the F baseline image is pre-write-buffer but also pre-everything-after-F. The overlays on top revert A, B, D as well. Verify `scenario_summary.stack_state` in the report confirms all flips took effect.
- Expected: cumulative delta >> any individual marginal delta. May also reveal whether the A-hurts-marginally finding (§5) holds when F is off — i.e., does A become standalone-beneficial again when the workload reverts?

### 6.5 (Optional) Standalone scenarios — `solo_*.json` set

For true standalone measurements, pair each of:

- `solo_pgbouncer_on.json` — image: pre-write-buffer, overlays: pg-defaults + dummy-cache + no-flusher (A on, B/D/F off)
- `solo_pg_tuning_on.json` — image: pre-write-buffer, overlays: no-pgbouncer + dummy-cache + no-flusher (B on, A/D/F off)
- `solo_query_cache_on.json` — image: pre-write-buffer, overlays: no-pgbouncer + pg-defaults + no-flusher (D on, A/B/F off)
- `solo_write_buffer_on.json` — image: tree HEAD, overlays: no-pgbouncer + pg-defaults + dummy-cache (F on, A/B/D off)

…against `before_all_optimizations.json` as the shared baseline. Five total runs, four comparisons. Nice-to-have for completeness, not required.

## 7. Outstanding issues

### 7.1 Server has no git → baseline image builds fail — **RESOLVED**

The thesis-server deploy is not a git checkout. Fix shipped:

1. `_apply_baseline_image_ref` accepts a `benchmark_image` field that bypasses git entirely.
2. `ensure_backend_image()` attempts `docker pull` when an explicit image is set but missing locally.
3. Workflow: build baseline locally (where git exists) → `docker tag` to `gashmurble/digitmile-baseline:*` → `docker push` → on server, scenario JSON sets `benchmark_image` and compose pulls on first use.

The F baseline (`gashmurble/digitmile-baseline:pre-write-buffer`) is pushed and validated end-to-end. C and E images still need to be built + pushed once those baselines are validated locally.

### 7.2 C and E baselines unvalidated

Both `baseline/pre-rollup-analytics` and `baseline/pre-ninja` git tags exist but no smoke scenario has been written or run against them. Expected friction:

- **E (pre-ninja, commit `9bb4925`)**: ingest URL was `/panel/insertRunData/` (or similar), not `/panel/api/runs/ingest/`. Current k6 scripts hit the new URL and will 404. Fix: either author a baseline-specific k6 script, or have the scenario pass an endpoint override env var.
- **C (pre-rollup-analytics, commit `2f0a317`)**: oldest baseline. `prepare_benchmark_dataset` CLI may differ; analytics endpoints may differ; rollup tables likely don't exist yet. Significant work.

Both are deferable. A, B, D, F + the four new scenarios in §6 already cover the strongest thesis claims.

### 7.3 Cold-cache vs warm-cache methodology

Not a scenario; a **two-run protocol** on the existing `realistic_school_day` scenario:

1. Run scenario, save report A.
2. Re-run scenario immediately, save report B.
3. A's dashboard p95 is cold-cache cost; B's is warm-cache. The delta is the cache hit rate's value.

For the D-reverted scenario both runs will look like cold. Comparing the four-cell table (D-on cold, D-on warm, D-off cold, D-off warm) shows what the cache contributes vs the warmth alone.

## 8. Methodology guardrails

To keep before/after comparisons honest:

1. **Same machine for paired runs.** Local-vs-server hardware differs; never mix. The thesis chapter records which host each run came from.
2. **Same dataset.** All `before_*.json` scenarios copy the `dataset:` block verbatim from their reference scenario. Cross-check via `dataset_report.weeks` in the report.
3. **Same script.** Re-using `mixed_weekly_cycle.js` for ingest-only scenarios is deliberate — diverging scripts would muddy the delta.
4. **Image verification.** `scenario_summary.image_info` in every report independently proves which image (and which commit, when SHA-tagged) produced the numbers.
5. **Stack state verification.** `scenario_summary.stack_state` shows actual PG settings, env vars, cache backend, and flusher image. Confirms the overlay actually changed runtime state.
6. **Marginal vs standalone framing** (§3). Every result table in the thesis chapter declares which type of measurement it reports.

## 9. Next steps in order

1. **Re-evaluate the four existing marginal comparisons** (§5) under the §3 marginal-vs-standalone framing. Confirm: PgBouncer surprise reproduces; PG tuning negligible matches the `pg_settings` inspection; cache modesty matches the 5-RPS interpretation; write-buffer headline holds. Optional confirming re-run for PgBouncer.
2. **Author the four §6 scenarios** in order:
   1. §6.4 `before_all_optimizations.json` — the headline chart, highest thesis ROI
   2. §6.1 `endurance_steady.json` — NFR-1, cheap to write
   3. §6.3 `mixed_steady.json` — NFR-3 + NFR-4
   4. §6.2 `overload_recovery.json` — NFR-5, most complex profile
3. **Run all four on local + server**, capture reports, generate comparison tables via `compare_reports.py`.
4. **Write the thesis evaluation chapter** using §2 NFRs as the structural skeleton: one section per NFR with a pass/fail verdict and headline number. Frame all per-optimization comparisons under §3.
5. (Optional) **Author and run the §6.5 solo standalone set** if time permits — would let the PgBouncer chapter conclude with both marginal and standalone numbers.
6. (Optional) **Validate C and E baselines.**

## 10. References

- `docs/research/ingest-capacity-model.md` — canonical capacity model the NFRs derive from
- `docs/decisions/write-buffering-adr.md` — F (the headline architectural change)
- `OPTIMIZATION_AUDIT.md` — proposed R1–R16, cited as future work
- `benchmarks/README.md` — operational guide
- `benchmarks/overlays/README.md` — overlay catalogue
- `benchmarks/sever_reports/reports/comparison_*.md` — the four marginal comparison reports from the server
