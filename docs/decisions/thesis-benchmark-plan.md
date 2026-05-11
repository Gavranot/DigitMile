# Thesis Benchmark Plan — Status, NFRs, Methodology, and Next Steps

**Status:** In progress (last updated 2026-05-11). Toggle harness operational on local + server. Four marginal comparisons (A, B, D, F) run on the production-target hardware. Ingest-route deep dive complete; PgBouncer removal decision pending operator validation. Four NFR-closing scenarios and the headline cumulative-effect scenario still to author.

**Audience:** A future maintainer (human or fresh LLM session) resuming this work cold. Sections 0–4 are orientation; 5 onward is operational.

---

## 0. Project orientation (read first)

**DigitMile** is a Unity WebGL math game played by primary-school students, paired with a Django/PostgreSQL backend that ingests per-turn gameplay telemetry and surfaces weekly analytics to teachers. It is the user's undergraduate thesis project at FINKI/UKIM (Skopje). The production target is a 2 vCPU / 3.8 GiB VPS in North Macedonia.

The thesis evaluation chapter has to answer:

1. **Capacity** — at the production target hardware, how much load can the system sustain? Where does it break?
2. **Optimization contribution** — six architectural optimizations were shipped over the lifetime of the project (A–F below). What did each one buy in measurable terms?
3. **Non-functional requirements** — does the system meet quantitative requirements (latency, throughput, recovery) derived from the deployment's capacity model?

Key external documents this plan depends on:

- `docs/research/ingest-capacity-model.md` — **canonical capacity model.** Defines the steady-state and lesson-bell-burst load regimes. T (turns/run) = 20; medium adoption = ~11 ingest RPS steady / ~29 RPS burst; high adoption = ~16 / ~44. All NFRs derive from §5 and §7 of this doc.
- `docs/decisions/write-buffering-adr.md` — the ADR for optimization F (the most architecturally significant change). The HTTP ingest path no longer touches PostgreSQL synchronously; it pushes to Redis, and a separate `flusher` process drains in batches.
- `docs/architecture.md` — one-page system map.
- `OPTIMIZATION_AUDIT.md` (repo root) — proposed R1–R16 work for *after* this thesis. Cited as future work, not in scope.
- `AGENTS.md` (repo root) — repo-wide LLM working instructions; respect it.

---

## 1. Architecture of the benchmark toggle system

The harness lets each shipped optimization be turned off so the thesis can produce before/after comparisons on identical hardware. Three tiers, each with a different mechanism:

### Tier 1 — code-level env flags (not currently used)

A `digitmileapi/optimizations.py` module was designed but not implemented (no shipped optimization needs runtime branching today). The flag pattern is documented in conversation history and is reserved for future small optimizations (R-series from `OPTIMIZATION_AUDIT.md`).

### Tier 2 — compose overlays (service-shape / config toggles)

YAML files under `benchmarks/overlays/`. Each one overrides specific services in `benchmarks/docker-compose.benchmark.yml`. Production compose files are never affected — overlays only apply to the benchmark stack.

| Overlay | Reverts | How |
|---|---|---|
| `no-pgbouncer.yml` | A — PgBouncer + Django pool settings | Replaces pgbouncer with busybox; backend/flusher set `DB_HOST=benchmark-db`, `DB_CONN_MAX_AGE=60`, `DB_DISABLE_SERVER_SIDE_CURSORS=False` |
| `pg-defaults.yml` | B — PG `synchronous_commit=off` + tuning | Strips `-c` flags from the postgres command, leaving PG 16 defaults |
| `dummy-cache.yml` | D — django-redis query cache | Sets `DJANGO_CACHE_BACKEND=dummy` |
| `no-flusher.yml` | (companion) | Stubs the flusher container with busybox; required when the baseline image predates the flusher command |

Settings.py reads `DB_CONN_MAX_AGE`, `DB_DISABLE_SERVER_SIDE_CURSORS`, `DJANGO_CACHE_BACKEND`, and `REDIS_URL` from env, all with defaults matching current production. Prod `.env` does not set them, so prod behavior is byte-identical.

### Tier 3 — baseline Docker images (for optimizations that deleted predecessor code)

Three optimizations (C, E, F) shipped by *deleting* the old code path. They can't be reverted by overlay; the harness builds the backend image from a historical git ref instead.

| Git tag | Predecessor of | Status |
|---|---|---|
| `baseline/pre-rollup-analytics` → `2f0a317` | C (rollup-only analytics, `22c9bfc`) | Image not yet built |
| `baseline/pre-ninja` → `9bb4925` | E (django-ninja + Pydantic, `6d77836`) | Image not yet built |
| `baseline/pre-write-buffer` → `6d77836` | F (Redis write buffer, `e27b758`) | **Image built + pushed + validated** |

Scenario JSON fields:

- `benchmark_image_ref`: a git ref. Resolved locally via `git worktree add` + `docker build`. Fails on hosts without `.git/` (e.g., the deployment server).
- `benchmark_image`: an explicit Docker image tag. Bypasses git. Compose pulls if missing locally. **Use this on the server.** When both are set, `benchmark_image` wins; the ref is kept for documentation.

Pushed images live under `gashmurble/digitmile-baseline:<short-name>` on Docker Hub.

### Toggle helpers in `run_scenario.py`

- `_apply_baseline_image_ref()` — selects `benchmark_image` or builds from `benchmark_image_ref`.
- `_resolve_overlay_paths()` — resolves `scenario.compose_overlays` filenames; **also force-appends `no-pgbouncer.yml` when `BENCHMARK_DISABLE_PGBOUNCER` env var is truthy**, and routes reports under `benchmarks/reports/no_pgbouncer/` so the without-PgBouncer set doesn't overwrite the with-PgBouncer set.
- `verify_backend_image()` — after stack is up, queries the running container and aborts if the actual image doesn't match what the scenario asked for.
- `verify_stack_state()` — queries PG `pg_settings`, backend env vars, the live Django `CACHES['default']['BACKEND']` value, and the flusher image. Confirms overlays actually changed runtime state (not just that docker compose was given the overlay file). Embedded in every report's `scenario_summary.stack_state`.

---

## 2. The six "big" optimizations under evaluation

Chronological order of shipping, with the commit that introduced each. The audit's R-series proposals are out of scope.

| # | Optimization | Shipping commit | Reversal mechanism | Run status |
|---|---|---|---|---|
| A | PgBouncer transaction-pool + Django `CONN_MAX_AGE=0` + `DISABLE_SERVER_SIDE_CURSORS=True` | `03fae64` | `no-pgbouncer.yml` overlay | ✅ Local + server |
| B | PostgreSQL `synchronous_commit=off` + `shared_buffers`, `work_mem`, etc. | `4abbbe3` | `pg-defaults.yml` overlay | ✅ Local + server |
| C | Rollup-only analytics (dashboard reads stopped touching hot `TurnEvent` rows) | `22c9bfc` (+ earlier `2f0a317`, `00c9b8e`) | `baseline/pre-rollup-analytics` image | ⚠ Unvalidated |
| D | django-redis query cache + 7-day TTL + invalidation on ingest | `c04dddb` + `f6dd831` | `dummy-cache.yml` overlay | ✅ Local + server |
| E | django-ninja + Pydantic v2 (Rust) ingest endpoint (replaced DRF) | `6d77836` + `66af872` | `baseline/pre-ninja` image | ⚠ Unvalidated; expected to need k6 URL fix |
| F | Redis write-buffered ingest + separate flusher service | `e27b758` | `baseline/pre-write-buffer` image + `no-flusher.yml` | ✅ Local + server |

---

## 3. Non-Functional Requirements

NFRs are anchored to the canonical capacity model so each is defensible. Numbers below correspond to **medium adoption (50%)** unless noted, on the production target hardware (2 vCPU / 3.8 GiB).

| ID | Requirement | Capacity-model source |
|---|---|---|
| **NFR-1** | Sustain **11 ingest RPS for 15 min** with p95 < 1000 ms, ≤ 0.5% dropped iterations, backend CPU avg < 90% | §7 steady-state, medium |
| **NFR-2** | Absorb a **60 s burst of 29 RPS** with zero 5xx, p95 < 2000 ms, and Redis `ingest_buffer` drains to 0 within 30 s of burst end | §5 lesson-bell, medium |
| **NFR-3** | **Dashboard p95 < 3000 ms** during NFR-1 traffic (teachers reading during class) | Realistic mixed regime |
| **NFR-4** | **Friday compaction** completes within 60 s for one teacher's week with no dropped k6 iterations on a concurrent 1 req/s mixed read load | Operational |
| **NFR-5** | **After a deliberate 5-min overload at 2× capacity** (22 RPS), the system returns to NFR-1 baseline p95 within 2 min once load drops to 11 RPS | Resilience |

For **high adoption (75%)** the same NFRs scale to 16 RPS steady / 44 RPS burst — captured by re-running the same scenarios at bumped rates, not by authoring separate scenarios.

Each NFR maps to **one scenario** and produces **one pass/fail line** in the thesis evaluation chapter.

---

## 4. Methodology: marginal vs standalone vs cumulative

**This is the most important conceptual distinction in the evaluation chapter.** It must be stated explicitly before any result table.

The four `before_X.json` scenarios each revert **only optimization X** while leaving the others on:

| Scenario | A | B | D | F |
|---|---|---|---|---|
| `before_pgbouncer_*` | **off** | on | on | on |
| `before_pg_tuning_*` | on | **off** | on | on |
| `before_query_cache_*` | on | on | **off** | on |
| `before_write_buffer_*` | on | on | on | **off** |
| Reference (`ingest_isolation`, `realistic_school_day`) | on | on | on | on |

This measures **marginal contribution** — "should we keep X in the current stack today?" — not **standalone contribution** — "did X help when it was first introduced?". The two can disagree when optimizations interact through the workload they create. The PgBouncer finding (§6) is exactly that.

Three measurement types the thesis can report:

- **Marginal** (this is what the four `before_*` runs produce): one optimization off, all others on.
- **Cumulative** (the `before_all_optimizations.json` scenario in §8): all four off vs all four on. The single headline chart.
- **Standalone** (optional `solo_*.json` set in §8): one optimization on, all others off. Most rigorous but requires five additional scenarios.

The evaluation chapter must declare which type each result table reports.

---

## 5. Coverage matrix

| Question the thesis needs to answer | Scenario(s) | Gap |
|---|---|---|
| Does each optimization help marginally? | `before_*` × 4 + reference | ✅ Covered (need to re-frame per §4) |
| Where's the throughput ceiling? | `ingest_isolation`, `stress_ramp` | ✅ Covered |
| Does it handle the burst regime? | `lesson_bell` | ✅ Covered |
| Sustained target load over **time** (NFR-1)? | — | ❌ No endurance test |
| Recovery from overload (NFR-5)? | — | ❌ Missing |
| **Cumulative** effect of all opts stacked? | — | ❌ Missing (headline chart) |
| Does it meet declared NFRs (pass/fail)? | — | ❌ Missing (NFRs 1–5) |
| Scales with data volume? | partial via `mixed_semester_*` | ⚠ Indirect |
| Cold-cache vs warm-cache for D? | — | ❌ Two-run protocol on existing scenario |
| Compaction degrade reads? | `compaction_under_read_load` | ✅ Covered |
| Standalone (each-vs-bare-baseline)? | — | ⚠ Optional |

The credibility-critical gaps are **endurance**, **overload recovery**, and the **cumulative comparison**.

---

## 6. Results so far (marginal comparisons, server runs, 2026-05-11)

All four marginal comparisons ran on the production server. Headline:

| Comparison | Reverted | http_req_duration.avg | p95 | drops | load_health | Reading |
|---|---|---|---|---|---|---|
| **A — PgBouncer** | A off vs A on | 10.66 → 412.88 ms | 23.47 → 1829.56 ms | 0 → 86 | green → yellow | **A hurts marginally** (40× latency); interaction with F |
| **B — PG tuning** | B off vs B on | 412.49 → 412.88 ms | 2016.82 → 1829.56 ms | 103 → 86 | yellow → yellow | **Near-zero**; tuned values mostly match PG 16 defaults |
| **D — Query cache** | D off vs D on | 238.07 → 194.95 ms | 928.97 → 862.90 ms | — → — | green → green | Modest 18% at 5 RPS mixed (scales with concurrency) |
| **F — Write buffer** | F off vs F on | 811.69 → 412.88 ms | 3563.96 → 1829.56 ms | 177 → 86 | yellow → yellow | **Headline win**: ~50% latency, drops halved |

Raw reports live under `benchmarks/sever_reports/reports/comparison_*.md` (the folder name is misspelled "sever" — leave it; the user explicitly chose that naming).

### Interpretive notes (fold into the thesis chapter)

- **A — PgBouncer (negative marginal contribution).** Frame as interaction effect under §4. The original commit was correct under the pre-F workload (every request synchronously wrote a Run + ~30 TurnEvent rows); F flipped the cost-benefit. With F active, the HTTP ingest path touches PG for one sub-ms `Student.exists()` check per request — PgBouncer's per-request handshake (forced by `CONN_MAX_AGE=0`) now exceeds the savings from pooling.

  The fairness of the comparison was challenged in conversation. Verdict: the comparison **is fair** — it measures each mode in its production-style configuration (PgBouncer with `CONN_MAX_AGE=0`, no-PgBouncer with `CONN_MAX_AGE=60`). Two settings move together because PgBouncer transaction mode *requires* `CONN_MAX_AGE=0`.

- **B — PG tuning (negligible).** Consistent with pre-run `pg_settings` inspection: six of eight `-c` flags duplicate PG 16 defaults. Only `synchronous_commit=off` and `random_page_cost=1.1` differ. At this workload, writes mostly land in Redis first, so commit semantics affect the flusher, not the HTTP path.
- **D — Query cache (modest at single-teacher load).** 5 RPS single-teacher = limited cache reuse opportunity. Value scales with concurrent dashboard users hitting overlapping queries — not measured. A follow-up scenario at 10 concurrent teachers would quantify.
- **F — Write buffer (the headline).** Matches the ADR's prediction. ~50% latency, ~50% fewer drops, ~20% lower backend CPU. The headline chart of the evaluation chapter.

### Ingest-route deep dive (A — PgBouncer)

Beyond the HTTP latency the comparison helper shows, the full ingest pipeline behaves as follows when PgBouncer is removed:

| Layer | With PgBouncer | Without PgBouncer | Δ |
|---|---|---|---|
| HTTP req median | 38.1 ms | 7.4 ms | -81% |
| HTTP req p90 | 1513 ms | 18.1 ms | -98.8% |
| HTTP req p95 | 1830 ms | 25.0 ms | -98.6% |
| HTTP req avg | 412.9 ms | 10.7 ms | -97% |
| Dropped iterations | 86 | 0 | — |
| Backend CPU avg | 56.28% | 28.63% | -49% |
| Backend CPU peak | 99.40% | 72.16% | -27% |
| Flusher CPU avg | 17.95% | 18.66% | flat |
| Flusher memory peak | 137 MB | 112 MB | -18% |
| DB CPU avg | 23.87% | 25.79% | +8% |
| DB CPU peak | 73.10% | 112.03% | +53% (one vCPU pegged briefly) |
| Redis commands processed | 24,583 | 27,442 | +12% |
| Redis cache hit rate | 69.4% | 71.8% | +2.4 pp |

Reading: removing PgBouncer doesn't just speed up HTTP requests, it lets the **whole pipeline move more work**. Backend CPU drops by half (giving 2× capacity headroom). Flusher drains more aggressively (lower memory peak). DB takes the load directly but stays well under budget on average. **Decision pending: PgBouncer to be temporarily disabled in production for validation.** See §7.

---

## 7. Open production decisions

### PgBouncer removal — pending operator validation

User has run the full comparison set (with `BENCHMARK_DISABLE_PGBOUNCER=1`) on local + server and seen consistent latency wins without PgBouncer. The decision criterion stated: "if I see lower numbers, I'm getting rid of it."

What still needs to happen before flipping production:

1. **Re-run B, D, F marginal comparisons in the no-PgBouncer regime** (the toggle env var is wired and the reports route to `benchmarks/reports/no_pgbouncer/`). Confirm each individual optimization still shows the expected effect or improves further.
2. **A confirming production toggle plan.** The benchmark toggle is benchmark-only by design. Production removal requires:
   - Switching `DB_HOST` to `db` (or equivalent) in production `.env`
   - Setting `DB_CONN_MAX_AGE=60` and `DB_DISABLE_SERVER_SIDE_CURSORS=False` in production `.env`
   - Stopping the `pgbouncer` service in `docker-compose.yml`
   - Or, cleaner: a `docker-compose.no-pgbouncer.yml` overlay for the prod compose stack mirroring the benchmark one (not yet authored; user explicitly scoped the current toggle to benchmark-only)

   Connection-count safety check: with 5 gunicorn workers + 1 flusher = ~6–7 PG connections at steady state. PG default `max_connections` = 100. 14× safety margin. No risk of exhausting PG connections.

3. **A rollback plan.** Simply unsetting the env vars and re-adding pgbouncer to docker-compose.yml restores the original behavior. The settings.py defaults already match the with-PgBouncer configuration.

---

## 8. Scenarios remaining to author

Naming convention: snake_case under `benchmarks/scenarios/`. Each new scenario gets a paired `before_*` companion if it's a comparison.

### 8.1 `before_all_optimizations.json` — the cumulative headline chart

- `benchmark_image_ref: baseline/pre-write-buffer`
- `benchmark_image: gashmurble/digitmile-baseline:pre-write-buffer` (for server)
- `compose_overlays: ["no-pgbouncer.yml", "pg-defaults.yml", "dummy-cache.yml", "no-flusher.yml"]`
- Paired with current-tree `national_medium.json`
- **The single most impactful chart in the thesis.** All four optimizations off vs all four on, identical hardware.
- Caveat: the F baseline image is also pre-everything-after-F. Overlays on top revert A, B, D. Verify `scenario_summary.stack_state` confirms all flips landed.

### 8.2 `endurance_steady.json` — closes NFR-1

- 11 ingest RPS sustained for 15 min (no ramp)
- Dataset: `national_medium` scale (~1,000 students, 2 hot weeks)
- Watch: `LLEN ingest_buffer` over time (stay near zero), backend memory (no creep), p95 latency (no walk-up)
- Pass: zero drops, p95 < 1000 ms across the full window, CPU avg < 90%

### 8.3 `mixed_steady.json` — closes NFR-3 and NFR-4

- 11 ingest RPS + 4 read classes at 1 req/s each (dashboard, analytics, turn_insights, replay) for 10 min
- Optional Friday-compaction trigger via `verification.compact_after_traffic_week_index`
- Dataset: `national_medium` scale
- Pass: dashboard p95 < 3000 ms, analytics p95 < 5000 ms, compaction < 60 s with no read drops

### 8.4 `overload_recovery.json` — closes NFR-5

- Three phases via `ramping-arrival-rate`: 2 min 0→22 RPS, 5 min hold at 22 RPS (2× capacity), 5 min recovery at 11 RPS
- Dataset: same as 8.2
- Watch: in phase 3, seconds until p95 returns < 1000 ms; seconds until `ingest_buffer` drains
- Pass: full recovery to NFR-1 baseline within 2 min of load drop

### 8.5 (Optional) Solo standalone scenarios

For true standalone measurement of each optimization. Pair each against `before_all_optimizations.json` as the shared baseline:

- `solo_pgbouncer_on.json` — image pre-write-buffer, overlays pg-defaults + dummy-cache + no-flusher (only A on)
- `solo_pg_tuning_on.json` — image pre-write-buffer, overlays no-pgbouncer + dummy-cache + no-flusher (only B on)
- `solo_query_cache_on.json` — image pre-write-buffer, overlays no-pgbouncer + pg-defaults + no-flusher (only D on)
- `solo_write_buffer_on.json` — image tree HEAD, overlays no-pgbouncer + pg-defaults + dummy-cache (only F on)

Nice-to-have; A, B, D, F marginal + the cumulative chart already cover the strongest claims.

---

## 9. Methodology guardrails

To keep comparisons honest:

1. **Same machine for paired runs.** Local hardware ≠ server hardware. The thesis chapter records which host produced each number.
2. **Same dataset.** Each `before_*.json` copies the `dataset:` block verbatim from its reference scenario. Cross-check via `dataset_report.weeks` in the report.
3. **Same script.** `mixed_weekly_cycle.js` is re-used across pure-ingest scenarios because reuse is the safer choice — diverging scripts muddy the delta.
4. **Image verification.** `scenario_summary.image_info` in every report proves which image (and which commit, when the tag is SHA-stamped) produced the numbers.
5. **Stack state verification.** `scenario_summary.stack_state` shows actual PG settings, env vars, cache backend, and flusher image. Confirms overlays actually flipped runtime state.
6. **Marginal vs standalone framing** (§4). Every result table in the chapter declares which type of measurement it reports.

---

## 10. Outstanding technical issues

### 10.1 C and E baselines unvalidated

Both git tags exist but no smoke scenario has been written. Expected friction:

- **E (`baseline/pre-ninja`, `9bb4925`)**: ingest URL was `/panel/insertRunData/` (or similar), not `/panel/api/runs/ingest/`. Current k6 scripts will 404. Fix: baseline-specific k6 script, or an endpoint-override env var.
- **C (`baseline/pre-rollup-analytics`, `2f0a317`)**: oldest baseline. `prepare_benchmark_dataset` CLI may differ; analytics endpoints may differ; rollup tables likely don't exist. Significant work.

Both deferable; A, B, D, F + the §8 scenarios already cover the strongest thesis claims.

### 10.2 Cold-cache vs warm-cache methodology

Not a new scenario; a two-run protocol on `realistic_school_day`:

1. Run scenario, save report A.
2. Re-run immediately, save report B.
3. A's dashboard p95 is cold-cache cost; B's is warm-cache. Delta is the cache hit rate's value.

For the D-reverted scenario both runs look cold. Comparing the four-cell table (D-on cold / D-on warm / D-off cold / D-off warm) splits cache value from warmup effect.

### 10.3 k6 doesn't emit p99 by default

The summary export contains p95 but not p99. Adding a `summaryTrendStats` option to each k6 script would surface it. Deferred — p95 is enough for the thesis.

### 10.4 `dropped_iterations` is omitted when zero

k6 only emits the metric when it has data. A "—" in the comparison helper for this field means zero drops, not missing data. The `load_health: green` field independently confirms.

---

## 11. Next steps in priority order

1. **Re-run B, D, F marginal comparisons with `BENCHMARK_DISABLE_PGBOUNCER=1`** to see whether each optimization's contribution holds (or improves) in the no-PgBouncer regime. Reports land under `benchmarks/reports/no_pgbouncer/`. Compare against the with-PgBouncer set already in `benchmarks/sever_reports/reports/`.
2. **Author `before_all_optimizations.json`** (§8.1) — the cumulative headline chart. Highest thesis ROI of any remaining work.
3. **Author `endurance_steady.json`** (§8.2) — cheap to write, closes NFR-1, proves the system is stable over time, not just for 4-minute ramps.
4. **Author `mixed_steady.json`** (§8.3) — closes NFR-3 and NFR-4 together.
5. **Author `overload_recovery.json`** (§8.4) — closes NFR-5, most complex profile, but strongest resilience claim.
6. **Decide PgBouncer removal in production** based on §11.1 results. If green across the board, author a `docker-compose.no-pgbouncer.yml` for the production stack mirroring the benchmark overlay.
7. **Write the thesis evaluation chapter** using §3 NFRs as the structural skeleton: one section per NFR, pass/fail verdict, headline number, link to the report. Frame every per-optimization comparison under §4.
8. (Optional) Solo standalone set (§8.5).
9. (Optional) Validate C and E baselines.

---

## 12. File index

### Plan and decision docs

- `docs/decisions/thesis-benchmark-plan.md` — **this file.** The resume-point for the thesis evaluation work.
- `docs/decisions/write-buffering-adr.md` — ADR for optimization F.
- `docs/decisions/capacity-math-correction.md` — outdated, kept with a banner pointing to the canonical model below.
- `docs/research/ingest-capacity-model.md` — canonical capacity model.

### Benchmark harness

- `benchmarks/run_scenario.py` — entry point. Reads a scenario JSON, brings up an isolated compose stack, seeds data, runs k6, captures the report.
  - Key fields read from scenario JSON: `name`, `dataset`, `traffic`, `compose_overlays`, `benchmark_image_ref`, `benchmark_image`, `verification`, `report_output`.
  - Env vars read: `BENCHMARK_BACKEND_IMAGE`, `BENCHMARK_DISABLE_PGBOUNCER`, `BENCHMARK_KEEP_STACK`, `BENCHMARK_DB_NAME`, `BENCHMARK_DB_USER`, `BENCHMARK_DB_PASS`.
- `benchmarks/docker-compose.benchmark.yml` — the benchmark stack (separate from production).
- `benchmarks/overlays/*.yml` — Tier-2 overlay catalogue.
- `benchmarks/k6/*.js` — k6 scripts. `mixed_weekly_cycle.js` is the canonical multi-class script; per-class rate of 0 makes that class skip.
- `benchmarks/scenarios/*.json` — scenario definitions.
- `benchmarks/compare_reports.py` — pairs two reports and emits a markdown delta table.
- `benchmarks/reports/` and `benchmarks/sever_reports/reports/` — generated reports. The latter is the user's snapshot of server-side runs ("sever" misspelling is intentional, do not rename).

### Backend code paths touched by the toggle system

- `DigitMilePanel/digitmile/settings.py` — env-driven branches for `DB_CONN_MAX_AGE`, `DB_DISABLE_SERVER_SIDE_CURSORS`, `DJANGO_CACHE_BACKEND`, top-level `REDIS_URL`. Defaults match current production exactly.
- `DigitMilePanel/digitmileapi/ingest_router.py` — the live ingest endpoint. Reads `settings.REDIS_URL` directly (not via CACHES) so the dummy-cache overlay doesn't break ingest.
- `DigitMilePanel/digitmileapi/management/commands/flush_ingest_buffer.py` — the flusher. Same fix.
- `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py` + `rebuild_weekly_rollups.py` — `cache.delete_pattern(...)` is feature-detected (skips on `DummyCache`).

### Production safety

- `docker-compose.yml`, `docker-compose.prod.yml` — production compose, **untouched** by the benchmark toggle system. The benchmark stack is fully isolated.
- The PgBouncer removal decision (§7) is the only pending production change.

---

## 13. User preferences and communication style

From auto-memory; respect these throughout the conversation:

- **Single docs location.** Everything under `docs/`. Don't scatter into app subfolders.
- **Outdated, not deleted.** When a doc is superseded, mark it outdated with a pointer to the replacement; don't delete.
- **No hot data in dashboard.** Dashboard reads only from rollup tables (this is optimization C).
- **k8s is scaffolding.** `k8s/` directory is outdated placeholder. Mention in one line at most.
- **Single ingest path.** `runs/ingest/` is the sole Unity endpoint. `flush_ingest_buffer` is a hard runtime dependency.

User context: undergraduate thesis student, tight schedule, technically strong, asks sharp methodology questions. Prefers concise answers grounded in measurable evidence. The auto-memory file `MEMORY.md` is the index; individual entries live next to it.

---

## 14. References

- `docs/research/ingest-capacity-model.md` — capacity model
- `docs/decisions/write-buffering-adr.md` — F ADR
- `OPTIMIZATION_AUDIT.md` — future-work proposals
- `benchmarks/README.md` — operational guide for running scenarios
- `benchmarks/overlays/README.md` — overlay catalogue
- `benchmarks/sever_reports/reports/comparison_*.md` — the four marginal comparison reports from the server
