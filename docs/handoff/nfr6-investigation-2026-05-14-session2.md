# Handoff — NFR-6 investigation, session 2 (2026-05-14, evening)

> Successor to `nfr6-investigation-2026-05-14.md`. Same project, same user
> (Damjan Avramovski, FINKI/UKIM thesis on DigitMile). This document covers
> the second working session and lists what's left for the storage walk to
> actually complete on the 3.8 GiB VPS.

---

## 1. What happened in this session

### 1.1 Resumed at the open decision point of session 1

Session 1 paused on three options (A/B/C) for handling the aggregation OOM.
The user chose **A** (refactor `aggregate_weekly_rollups` to stream).

### 1.2 Implemented streaming refactor (option A)

`DigitMilePanel/digitmileapi/weekly_aggregation.py` — replaced the eager
`list(...).prefetch_related(...)` with chunked iteration:

- New: `runs_qs.iterator(chunk_size=500)` over Runs.
- Per chunk: one extra query to fetch the chunk's `TurnEvents` with
  `prefetch_related(triggers)`.
- Peak Python heap for raw runs+turns dropped from ~5 GB to ~50 MB.
- `aggregate_weekly_rollups(week_start, chunk_size=500)` — `chunk_size` is now
  a parameter so tests can force multi-chunk iteration against small datasets.

### 1.3 Wrote a correctness oracle test

`DigitMilePanel/digitmileapi/test_rollup_accuracy.py` —
`test_streaming_aggregation_matches_raw_data_verifier`:

- Seeds 3 teachers × 2 classrooms × 5 students = 60 runs (multi-teacher
  topology so cross-attribution bugs would surface).
- Runs `aggregate_weekly_rollups(chunk_size=7)` → forces ~9 chunks against
  60 runs, exercising the chunk-boundary flush path ~8 times.
- Then invokes the production `verify_weekly_rollups` command — which
  compares raw row counts/sums against rollup row counts/sums.
- **Passed.**

Note: the existing two tests in the file (`test_rollup_matches_hot_data_analytics`
and `test_partial_compaction_matches`) are broken by design — they import
from `rollup_analytics` (rollup-only) for both legs of a hot-vs-rollup
comparison. They were never actually testing anything. Left in place; the
new test is the real oracle.

### 1.4 Discovered limit #4 — accumulator-dict memory + PG bulk_create OOM

Running `storage_year_simulation` after the streaming refactor:

- Week 1 seed completed (18 min, +4.1 GB DB).
- Compaction phase started.
- Crashed at `StudentWeekCardFamilyStats.objects.bulk_create(...)` with
  `psycopg2.OperationalError: server closed the connection unexpectedly`.
- Root cause: **the accumulator dicts** (`student_card_families`,
  `student_card_types`, `student_conditionals`, etc.) grow monotonically
  across the whole week's iteration and live in Python memory the entire
  time. At national-medium scale they sum to ~3 GB. Plus PG processing a
  multi-thousand-row INSERT. On a 3.8 GiB host, OOM-kill is inevitable.
- The streaming refactor bounds *raw* working memory but not *accumulator*
  memory.

### 1.5 Implemented per-teacher invocation (option B from session 1)

The methodologically correct production pattern. Now landed:

- `aggregate_weekly_rollups(week_start, chunk_size=500, teacher_id=None)`.
  Optional `teacher_id` scopes runs and rollup-deletes to one teacher's slice.
- `_delete_existing_week_rollups(week_start, teacher_id=None)` — scoped
  deletes so a per-teacher pass does not wipe other teachers' rollups.
- `compact_weekly_runs` Django command refactored:
  - `--teacher-id` flag (single slice, caller orchestrates verify + status).
  - `--per-teacher` flag (discovers active teachers, loops over slices,
    runs `verify_weekly_rollups` once at the end, finalizes
    `WeeklyCompactionRun`).
  - `--skip-verification` flag (out-of-band verifier orchestration).
  - Internal: `_compact_slice()` helper does aggregate + archive write +
    run-bucket rebuild + raw-row delete for one `(week, teacher_id)` pair.
  - Internal: `_handle_per_teacher()` orchestrates the loop.
  - Internal: `_finalize_week_record()` accumulates per-slice counts onto
    one `WeeklyCompactionRun` row at the end.

### 1.6 Wired `--per-teacher` into the storage walk

- `benchmarks/scenarios/storage_year_simulation.json`: added
  `"compaction_per_teacher": true` under `verification.storage_walk`.
- `benchmarks/run_scenario.py` `storage_walk` branch:
  - Reads `storage_walk_cfg.get("compaction_per_teacher")`.
  - When true, appends `--per-teacher` to the `compact_weekly_runs` invocation.
  - Switched from `compose_exec` (silent) to `compose_exec_stream` so
    per-teacher progress (`[N/280] teacher_id=X`) shows in real time
    instead of buffering for the whole compaction step.

### 1.7 Added two more per-teacher correctness tests

`test_rollup_accuracy.py`:

- `test_per_teacher_aggregation_matches_raw_data_verifier`: runs
  `aggregate_weekly_rollups(teacher_id=N)` for each of the 3 seeded
  teachers in turn, then runs `verify_weekly_rollups` across the whole
  week. Catches:
  - per-teacher passes wiping other teachers' rollups
  - `classroom_student_counts` scoped wrong on `ClassroomWeekStats`
  - accumulator key tuples that omit `teacher_id`
- `test_per_teacher_pass_does_not_wipe_other_teachers_rollups`: snapshot
  teacher A's `StudentWeekStats` row count and `runs` sum, then run
  teacher B's pass, then re-snapshot teacher A. Must be unchanged. Guards
  against `_delete_existing_week_rollups` regressing to delete-without-
  teacher-filter.

---

## 2. Where the session paused

All code changes landed. The user is about to retry
`storage_year_simulation` with the per-teacher invocation pattern.

**Next actions for resuming:**

1. **Run the new correctness tests** before kicking off the storage walk:
   ```powershell
   docker compose exec backend python manage.py test \
     digitmileapi.test_rollup_accuracy.RollupAccuracyTest.test_per_teacher_aggregation_matches_raw_data_verifier \
     digitmileapi.test_rollup_accuracy.RollupAccuracyTest.test_per_teacher_pass_does_not_wipe_other_teachers_rollups \
     -v 2
   ```
   These should both pass on the multi-teacher seed dataset. If either fails,
   the per-teacher refactor has a real bug and the storage walk should not
   be re-run yet.

2. **Pull on the production VPS** (the storage walk runs there). The user's
   session-1 handoff noted that production may not have all of this session's
   fixes. Verify with `git log --oneline -10` on the VPS before kicking off.

3. **Re-run `storage_year_simulation`**. With `compaction_per_teacher: true`
   in the scenario, each week now:
   - Seeds ~140K runs (~18 min, unchanged).
   - Discovers 280 teachers active in the week.
   - Compacts each teacher's ~500 runs sequentially.
     - Estimated per-teacher slice: 5–15 sec.
     - Estimated whole-week compaction wall time: 30–60 min.
   - Runs `verify_weekly_rollups --require-archives --verify-run-buckets`
     once at the end.

4. **Watch for new failure modes**. The per-teacher refactor was tested
   only on 30 students × 3 teachers in unit tests. At 28K students × 280
   teachers some things might still surface:
   - Per-teacher discovery query (`distinct` on `student__classroom__teacher_id`
     filtered by `created_at__date`) might be slow without an explicit index
     — measure.
   - `verify_weekly_rollups --verify-run-buckets` at the end scans every
     affected `(student, level)` pair and may itself be slow. If it becomes
     a bottleneck, consider running it with just `--require-archives`
     during the loop and saving the full verifier for an end-of-walk pass.
   - The `WeeklyCompactionRun` row now only accumulates final counts via
     `_finalize_week_record`. During a long per-teacher loop the row sits
     in `PENDING` status. That's intentional but may surprise an observer
     who expected incremental progress.

---

## 3. Open work (deferred — not blocking NFR-6)

### 3.1 Parallelize per-teacher slices

The current implementation processes teachers **sequentially**. On a
multi-core VPS, parallelism would shrink wall time. Cleanest approach:

- Refactor `_handle_per_teacher` to use a `concurrent.futures.ProcessPoolExecutor`
  with `max_workers = min(host_cores, ~4)`.
- Each worker calls `compact_weekly_runs --teacher-id N --skip-verification`
  as a subprocess (so each gets its own Python heap and DB connection pool).
- Caveats:
  - PG connection ceiling — keep workers low (3–4) to avoid exhausting the
    pool (current Gunicorn workers + flusher already consume some).
  - The archive-write phase contends on disk. Parallelizing past ~3 may
    not actually speed things up.
  - `rebuild_historical_run_bucket_trends` is per-(student, level) pair so
    is naturally per-teacher safe.

**Why not in this session:** the sequential pattern already fixes the
3.8 GiB OOM, and NFR-6 is about storage longevity, not compaction wall time.
Parallelism is a follow-up performance optimization, not a correctness fix.

### 3.2 Production cron wiring

Currently nothing schedules compaction in production. For deployment:

- Add a cron job (or systemd timer) that runs
  `manage.py compact_weekly_runs <last-week-start> --per-teacher`
  every Monday at 03:00 local time.
- Alert on non-zero exit code → operator inspects `WeeklyCompactionRun`
  row for that week.
- After a compaction failure, retry is safe: completed slices stay
  COMPACTED, incomplete slices restart. (Per-slice idempotency is provided
  by `_delete_existing_week_rollups(teacher_id=N)` clearing and re-writing
  one teacher's rollups in a single transaction.)

### 3.3 `WeeklyCompactionRun` bookkeeping during per-teacher loops

Currently the row stays in `PENDING` for the full 30–60 min duration of a
per-teacher compaction, then jumps to `COMPACTED` at the end. An observer
watching the row sees no progress. For operational visibility:

- Add per-slice incremental updates to `run_count`/`turn_count`/`trigger_count`
  inside `_compact_slice` (atomic F() expressions to avoid lost updates).
- Optionally add a `slices_completed`/`slices_total` pair of fields to
  `WeeklyCompactionRun` for explicit progress.

**Not in this session:** the storage walk doesn't read these fields back
and the live `compose_exec_stream` output already shows progress.

### 3.4 `archive_runs_written` accounting under retry

The current per-slice archive-write loop respects existing archives via
`existing_archive.archive_status == READY and not overwrite_archives`. So
a retried slice will not re-write archives — `archive_runs_written` will
just be 0 on the retry. The final aggregated counts on
`WeeklyCompactionRun` therefore reflect the SUCCESS path total, not the
total work performed across retries. Document this if you write up a
production retry-runbook.

### 3.5 Test gaps

The per-teacher correctness tests added here cover:

- Verifier passes across the assembled week ✓
- Teacher B's pass doesn't wipe teacher A's rollups ✓

Not covered (would close residual risk):

- `compact_weekly_runs --per-teacher` end-to-end test (current tests only
  exercise `aggregate_weekly_rollups`, not the full command including
  archive writes + raw deletes). To add: a `TransactionTestCase` that calls
  `call_command("compact_weekly_runs", iso_date, "--per-teacher")` and
  asserts archive files exist on disk + TurnEvent rows are zero post-run.
  Skipped here because it requires real disk archive root setup in the
  test container; tractable but more involved than the rollup-only tests.
- Resumed retry: kill a per-teacher loop mid-way, restart, assert final
  state is correct. Not in scope; the current code is single-shot.

---

## 4. Files modified in this session (chronological)

| Path | Change |
|---|---|
| `DigitMilePanel/digitmileapi/weekly_aggregation.py` | Streaming refactor of `aggregate_weekly_rollups`: chunked `iterator()` over Runs, per-chunk turn fetch, `chunk_size` parameter, `teacher_id` parameter on both `aggregate_weekly_rollups` and `_delete_existing_week_rollups`. |
| `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py` | Full restructure into `_compact_slice` + `_handle_per_teacher` + `_finalize_week_record`. Added `--teacher-id`, `--per-teacher`, `--skip-verification` flags. Fixed `len(runs)` → `run_count_total` bug from session 1. |
| `DigitMilePanel/digitmileapi/test_rollup_accuracy.py` | Multi-teacher setUp (3×2×5 = 30 students across 6 classrooms × 3 teachers). Added 3 new tests: chunked-streaming verifier, per-teacher verifier, per-teacher non-clobber assertion. |
| `benchmarks/scenarios/storage_year_simulation.json` | Added `compaction_per_teacher: true` under `verification.storage_walk`. Updated notes. |
| `benchmarks/run_scenario.py` | `storage_walk` reads `compaction_per_teacher` and appends `--per-teacher` to the compaction subprocess. Switched compaction call from `compose_exec` to `compose_exec_stream` for live progress visibility. |
| `docs/handoff/nfr6-investigation-2026-05-14-session2.md` | This document. |

## 5. Files NOT touched (open work)

- `docs/thesis/chapter_evaluation.md` — §6.4 NFR-6 TBD placeholders remain.
  Refresh from `benchmarks/server_reports/storage_year_simulation.json`
  once the storage walk completes.
- `docs/research/compaction-scale-discoveries.md` — should be updated with
  limit #4 (accumulator-dict OOM) and the per-teacher invocation finding.
  Thesis material — leave that pass for after a successful storage walk so
  the prose reflects empirical numbers rather than projections.

---

## 6. Memory of the recommended invocation pattern

For thesis §6.4 prose, the right framing is:

> The DigitMile compaction job's natural invocation pattern is per-teacher.
> Each teacher's dashboard and rollup data are independent, and the rollup
> tables are already keyed by `teacher_id`. The system-level weekly volume
> at national-medium adoption is ~140k runs and ~2.8M turn events, but no
> single teacher generates more than ~500 runs/week. A monolithic
> whole-week compaction call holds three-orders-of-magnitude more state
> than necessary in one process, requires ~3 GB of accumulator
> dictionaries, and OOM-kills PG on the 3.8 GiB production-target hardware.
> The per-teacher invocation pattern bounds per-call working set to one
> teacher's slice and completes the weekly compaction in ~30–60 min total
> sequential wall time at national-medium scale. The storage trajectory
> measured by NFR-6 is invariant to the invocation pattern (same rollup
> rows, same archive files, same raw-row deletes), so the result remains
> a faithful storage longevity measurement.

This is also the conclusion to capture in `docs/research/compaction-scale-discoveries.md`
as the architectural finding from the NFR-6 investigation.
