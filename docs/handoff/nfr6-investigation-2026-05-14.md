# Handoff — NFR-6 investigation (2026-05-14)

> Pick-up notes for a fresh Claude session continuing the thesis evaluation work. The user is **Damjan Avramovski**, undergraduate at FINKI/UKIM (Skopje), writing a thesis on DigitMile. This session focused on NFR-6 (storage longevity) and hit a real architectural limit. The work paused at a decision point.

---

## 1. The project in one paragraph

DigitMile is a Unity WebGL math game played by primary-school students with a Django/PostgreSQL backend that ingests per-turn gameplay telemetry and surfaces weekly analytics to teachers. Production target: a 2 vCPU / 3.8 GiB VPS in North Macedonia. The thesis evaluation chapter answers three questions: (1) capacity at production target, (2) marginal contribution of 8 optimizations (A–H), (3) Non-Functional Requirements (latency, throughput, recovery, correctness, storage). Six NFRs. Five (NFR-1 through NFR-5 + reframed NFR-4) are already empirically closed against `benchmarks/server_reports/`. The chapter draft is at `docs/thesis/chapter_evaluation.md` (Macedonian Cyrillic, lab-report register).

## 2. What this session was working on

**NFR-6 — Storage longevity at full national medium adoption (27 900 students, 36 weeks, 10 GB target).** The user's thesis goal explicitly *includes* "make this work on production-target hardware". Sub-scale-with-extrapolation was considered but rejected by the user as methodologically weaker; **the storage scenario must run at full national-medium scale**.

A new scenario was authored: `benchmarks/scenarios/storage_year_simulation.json` (28 000 students × 36 weeks, iterative seed+compact, fail-fast disk safety thresholds).

The `run_scenario.py` `storage_walk` branch was added to orchestrate iterative seed-then-compact: it skips k6 traffic and pre/post analytics, seeds the population once via a new `--population-only` mode, then loops 36 times: append one week of runs → compact previous week → snapshot pg_database_size → disk safety check.

## 3. Where the session stuck

Three independent OOM / scale limits surfaced during the first attempted run at full national volume. **All three exist because the affected components were correctly sized for production per-school invocations** (≤500 Run rows per call) but the benchmark forces them through national aggregate (~140 000 Run rows per call). See `docs/research/compaction-scale-discoveries.md` for the full pre-fix snapshot and design-rationale-vs-discovered-limit analysis — that doc is the canonical write-up of the architectural tension and is thesis material.

**Status:**

| Limit | Site | Fixed? |
|---|---|---|
| #1 | Truncated 48-bit UUID in `TurnEvent.id` / `SpecialTileTrigger.id` defaults — birthday-paradox collisions at 100M+ rows | ✅ Fixed: seeder overrides ID with monotonic counter |
| #2 | `compact_weekly_runs.py` line 89: `runs = list(...)` materialises 140K Run rows | ✅ Fixed: streamed via `.iterator(chunk_size=500)`, queryset subquery filters downstream |
| #3 | `weekly_aggregation.py` line 174: `runs = list(...).prefetch_related(turn_events.prefetch_related(triggers))` — ~5 GB peak Python heap at national scale | ❌ **NOT FIXED** — pending user decision |

## 4. The pending decision

User was presented with three options for handling limit #3 and asked to choose. **No choice has been made yet.** Options as of paused state:

| | Approach | Effort | Thesis story |
|---|---|---|---|
| **A** | Refactor `aggregate_weekly_rollups` to stream `.iterator()` over Runs + per-run TurnEvent fetch | ~2 h code | "Discovered limit, fixed it, measured at full scale" |
| **B** | Restructure scenario to call `compact_weekly_runs` once **per teacher** (~280 calls/week) — matches production invocation pattern | ~1 h code (add `--teacher-id` filter to `compact_weekly_runs`, loop in storage_walk) | "Replicated production invocation pattern at scale" |
| **C** | Report finding as-is; reduce scenario population to where current pipeline fits (~5 000 students) + extrapolate | No code | "Aggregation pipeline limit constrains direct measurement; extrapolation per capacity model" |

Last recommendation in conversation was **B**. The user then asked a sharp follow-up: *"if I have a mechanism to test whether A messes with the actual logic of aggregation after the architectural change, that would be awesome"* — implying interest in (A) **if** correctness can be verified.

**Answer that wasn't yet given to the user:** Yes, such a mechanism exists. The Django management command `verify_weekly_rollups` (invoked from `compact_weekly_runs.py` lines 184–189) compares the in-DB rollup tables against a re-aggregation of the raw data. Any refactor of `aggregate_weekly_rollups` that produces a different output fails this verification immediately. Additionally there is a unit test `test_incremental_matches_batch_for_dashboard_rollups` that confirms the incremental rollup path produces identical output to the batch path. So (A) has a built-in correctness oracle — making (A) the strongest thesis option *if* the user accepts ~2h of refactor work.

**Resume by giving the user this correctness-oracle answer + asking them to confirm A vs B.**

## 5. Files modified in this session (chronological)

| Path | Change |
|---|---|
| `docs/thesis/chapter_evaluation.md` | New Macedonian chapter prose for NFR-1/2/3/4/5/6, optimizations F/D/B, G+H, A future-work; methodology §0.5; numbers refreshed from comparison_*.md. NFR-6 §6.4 has TBD placeholders pending empirical run. |
| `benchmarks/run_scenario.py` | Added `capture_storage_state()`, `check_disk_safety()`, full `storage_walk` branch (iterative seed+compact loop with disk-safety guards). Switches dataset prep to `--population-only` when `verification.storage_walk` present. Passes `--fast-bulk-insert` through to subprocess seeder calls. |
| `benchmarks/scenarios/storage_year_simulation.json` | New scenario: 280 teachers × 4 classrooms × 25 students = 28K students, 36 weeks, r_week=5, `fast_bulk_insert: true`, disk-safety ceilings (`min_host_free_bytes=4GB`, `max_pg_db_bytes=15GB`). |
| `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py` | Added module-level `_copy_escape`/`_copy_row` helpers, CLI flags `--population-only`/`--append-week-start`/`--fast-bulk-insert`, mode-branched `handle`, two new handler methods (`_handle_population_only`, `_handle_append_week`), branched `flush()` with COPY fast path (closure helpers `_fast_copy_turn_events`/`_fast_copy_special_tile_triggers`), and monotonic-counter ID override in `_generate_runs` to avoid birthday-paradox collisions. |
| `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py` | Replaced `runs = list(...)` with streamed `.iterator()`; build `run_ids` and `student_level_pairs` in the iterator pass; downstream filters use queryset subquery `runs_in_week` instead of `run__in=<list>`. |
| `docs/research/compaction-scale-discoveries.md` | New research doc capturing pre-fix code state and design rationale for each of the three scale limits. Thesis material. |

## 6. Files NOT yet modified (open work)

- `DigitMilePanel/digitmileapi/weekly_aggregation.py` — `aggregate_weekly_rollups` still has the 5 GB Python heap problem. Pending user choice between A/B/C.
- `docs/thesis/chapter_evaluation.md` §6.4 has TBD placeholders; populate from `benchmarks/server_reports/storage_year_simulation.json` once an empirical run completes.

## 7. Critical context to know

### 7.1 Capacity model
`docs/research/ingest-capacity-model.md` is canonical. National medium adoption = 27 900 present-adopted students, 10.6 RPS steady, 29.3 RPS burst, 139 500 runs/week, T=20 turns/run. `r_week = f × r_session = 2 × 2.5 = 5` (the storage scenario uses this). Do not invent numbers — derive from the model.

### 7.2 Per-teacher invariance argument
Dashboard queries are per-teacher. Each teacher only sees their own ~100 students regardless of total population. Index-based query plans give logarithmic dependence on total population — ≈35% more comparisons at 28K vs 1K students, not 28×. This is why sub-scale sampling is valid for *rate-driven* NFRs but NOT for *storage* (which scales linearly with N × time). The §0.5 methodology paragraph in `chapter_evaluation.md` codifies this.

### 7.3 PgBouncer
Removed from production after empirical comparisons (national_medium + national_high) showed it adds latency and CPU at all tested loads. NFR scenarios run **without PgBouncer** (`BENCHMARK_DISABLE_PGBOUNCER=1`). PgBouncer-on scenarios exist only as future-work A-comparisons in §9.3.

### 7.4 Thesis benchmark plan (older doc)
`docs/decisions/thesis-benchmark-plan.md` is a 2026-05-11 resume-point doc that predates this session. Some details (PgBouncer "pending operator validation") are outdated; the current source of truth is `chapter_evaluation.md`. Per user preference [[feedback_outdated_not_deleted]] the plan stays in place; don't delete.

### 7.5 User preferences (from auto-memory)
- Single docs location: everything under `/docs`. Don't scatter into app subfolders.
- Outdated, not deleted: mark superseded docs with a pointer rather than removing.
- No hot data in dashboard: dashboard reads only from rollup tables (this is optimisation C, baked in).
- k8s is scaffolding: outdated placeholder. Mention in one line at most.
- Single ingest path: `runs/ingest/` is the sole Unity endpoint; `flush_ingest_buffer` is a hard runtime dependency.
- Resume-point for benchmarks: `docs/decisions/thesis-benchmark-plan.md`. Open before any benchmark/scenario change.

### 7.6 User communication style
Sharp methodology questions; pushes back on hand-waving; appreciates honest acknowledgment of mistakes (I made several this session about scale assumptions and runtime estimates). Wants concise responses grounded in measurable evidence. Speaks Macedonian; chapter prose is in Macedonian Cyrillic, lab-report register.

## 8. Server-side state at handoff

The user had attempted to run `storage_year_simulation.json` twice:
- **Run 1**: hit limit #1 (PK collision in TurnEvent). User interrupted.
- **Run 2**: hit limit #2 + limit #3 (`exit 137` SIGKILL on `compact_weekly_runs` for week 2025-09-08). Container teardown completed; no orphan data because `with transaction.atomic():` rolled back.

Production server (`/var/www/digitmile`):
- Has all the fixes from this session pushed via git? **Not verified.** The user runs scenarios on the server; the working directory in this session was their local Windows checkout. They may need to `git pull` on the server before retrying.
- 40 GB disk, ~24 GB free, 3.8 GiB RAM.
- `benchmarks/server_reports/` contains 14 fresh JSON reports from a prior full run + 6 comparison_*.md files (May 14 timestamps). All NFR-1..NFR-5 evidence is intact.
- `storage_year_simulation.json` has NOT successfully completed once yet.

## 9. Order of operations to resume

1. **Tell the user about the `verify_weekly_rollups` correctness oracle** (covered in §4 above). Ask: A or B?
2. If user chooses **A**: refactor `aggregate_weekly_rollups` in `weekly_aggregation.py`. Stream via `.iterator()`. Build defaultdict aggregates incrementally. Re-test with `verify_weekly_rollups` against a small dataset first. Then retry full-scale run.
3. If user chooses **B**: add `--teacher-id` filter to `compact_weekly_runs` Django command. Modify `storage_walk` in `run_scenario.py` to loop over teachers per week. Retry full-scale run.
4. If user chooses **C**: scale `storage_year_simulation.json` down to ~5 000 students; update §6.4 of `chapter_evaluation.md` with explicit extrapolation language.
5. After a successful full run, refresh §6.4 of `chapter_evaluation.md` from `benchmarks/server_reports/storage_year_simulation.json` (fields `storage_trajectory_summary.baseline_db_bytes`, `final_db_bytes`, `net_growth_bytes`, `total_reclaimed_bytes`, `avg/max_compaction_duration_ms`, plus whether `max_pg_db_bytes` fail-fast triggered).

## 10. Quick file roadmap

For a fresh session to orient fastest, read in this order:
1. `docs/handoff/nfr6-investigation-2026-05-14.md` — this file
2. `docs/research/compaction-scale-discoveries.md` — pre-fix code state and rationale
3. `docs/thesis/chapter_evaluation.md` — current state of the chapter; §6 is the NFR-6 section
4. `docs/research/ingest-capacity-model.md` — canonical capacity numbers
5. `benchmarks/scenarios/storage_year_simulation.json` — the scenario in question
6. `benchmarks/run_scenario.py` — search for `storage_walk_active` to find the new code
7. `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py` — search for `fast_bulk_insert`, `_handle_append_week`, `next_turn_pk`
8. `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py` — the streamed version
9. `DigitMilePanel/digitmileapi/weekly_aggregation.py:164-181` — the **unfixed** OOM site

Auto-memory at `~/.claude/projects/C--Users-damja-Documents-Diplomska-DigitMile/memory/MEMORY.md` has the working notes. Do not duplicate to memory what's in this handoff doc — memory is for cross-session preferences and project-state; this handoff is operational pickup notes for one specific work-stream.
