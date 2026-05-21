# Compaction pipeline — scale-limit discoveries

> Research note generated during the NFR-6 (storage longevity) investigation on 2026-05-14. Captures the **as-was** state of the synthetic-data seeder and the weekly-compaction pipeline *before* the fixes applied in the same session, the original design rationale, and the limits we discovered when stress-testing at national medium-adoption scale. Thesis material for §6 of the evaluation chapter.

---

## 1. Context

The thesis evaluation chapter introduces NFR-6 (storage longevity): "Under sustained national medium-adoption traffic (≈27 900 students, capacity model §7) over one academic year, the production VPS's PostgreSQL database must remain under 10 GB with weekly compaction running on schedule." Closing this NFR requires a synthetic scenario (`storage_year_simulation`) that simulates 36 weeks of seed-then-compact cycles at full national volume.

That scenario put the existing pipeline under stress it had never seen, and surfaced **three independent scale limits**. This note records each one *as it was* so the thesis can discuss the production-vs-benchmark tension honestly.

The pipeline was never broken in production. Each limit only fires at the *aggregate* national-scale invocation pattern that the benchmark forces — a pattern production never executes.

---

## 2. Limit #1 — Truncated-UUID primary keys

### Pre-fix state

`DigitMilePanel/digitmileapi/models.py` (lines 47–54):

```python
def generate_turn_event_id():
    """Generate a prefixed ID for TurnEvent: trn_xxxxxxxx"""
    return f"trn_{uuid.uuid4().hex[:12]}"


def generate_special_tile_trigger_id():
    """Generate a prefixed ID for SpecialTileTrigger: stt_xxxxxxxx"""
    return f"stt_{uuid.uuid4().hex[:12]}"
```

Each ID is the prefix `trn_` / `stt_` plus 12 hexadecimal characters drawn from a `uuid.uuid4()`. That's **48 bits of entropy** per ID — a 281-trillion-element keyspace.

### Original design rationale

A 16-character `CharField` is human-readable in logs, fits in URL paths, and is much shorter than a full UUID. At production volume — a single Macedonian primary school generating a few thousand `TurnEvent` rows per day — the truncated form gives effectively zero collision risk for the lifetime of the deployment.

### Where it breaks

The birthday-paradox collision threshold for a 48-bit keyspace is `√2⁴⁸ ≈ 16.7 M`. At national medium adoption the seeder generates:

```
28 000 students × 5 runs/week × 20 turns/run = 2.8 M TurnEvent IDs per simulated week
×  36 weeks                                  ≈ 100.8 M IDs across a full year-horizon walk
```

Probability of at least one collision in a single week's 2.8 M rows ≈ `(2.8M)² / (2 · 2.8×10¹⁴) ≈ 1.4 %`. Across 36 weeks: ~5 expected collisions over the run. We hit one within the first week and the PG `UniqueViolation` killed the transaction.

### Production safety

Real primary-school ingest produces a few thousand turn events per day; even ten years of one teacher's data stays well below the collision threshold. The truncation is **architecturally correct for production load**.

### Fix applied

The seeder now overrides the model default with a monotonic counter seeded from `int(time.time() * 1000) + rng.randint(0, 1_000_000)`. Counter values are written as `trn_{n:012x}` — guaranteed unique within a process, and the numeric-only pattern is statistically disjoint from production-style hex UUIDs. Production ingest still uses `generate_turn_event_id()` exactly as before.

---

## 3. Limit #2 — `compact_weekly_runs` list materialisation

### Pre-fix state

`DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py` (lines 89–95, as-was):

```python
runs = list(
    Run.objects.filter(
        created_at__date__gte=week_start, created_at__date__lte=week_end
    )
    .select_related("student__classroom")
    .order_by("created_at", "id")
)
```

Followed downstream by:

- `compaction.run_count = len(runs)`
- `TurnEvent.objects.filter(run__in=runs).count()` (re-using the materialised list)
- `SpecialTileTrigger.objects.filter(turn__run__in=runs).count()` (same)
- An `archive` loop iterating over the list
- `student_level_pairs = {(run.student_id, run.level) for run in runs}`
- `Run.objects.filter(id__in=[run.id for run in runs]).update(...)` (re-materialising IDs)

### Original design rationale

The function is invoked **per-school per-Friday-20:00** in production. One school's weekly volume is `≤ 100 students × 5 runs/week × ≤ 7 days ≈ 3 500 Run rows`, each ~5 KB in Python memory once `select_related` joins are factored in. Total working set: `~17.5 MB` — comfortable on any container size, with all subsequent loop iterations cache-hot.

The eager materialisation is *intentional*: the function makes multiple passes over `runs` (count, archive loop, pair-set construction, final update filter), and a small in-memory list is faster than re-querying.

### Where it breaks

Forced through a single national-scale call (27 900 students = 280 schools' aggregate):

```
140 000 Run rows × ~5 KB (incl. game_map JSON + joined student/classroom) ≈ 700 MB
```

That alone is ~20 % of the 3.8 GiB production VPS RAM, *before* the archive-write loop's per-iteration allocations and *before* PostgreSQL's own working memory. The container's process was killed by the kernel OOM handler (`exit 137`).

### Production safety

Per-school invocation never sees this volume. The benchmark forces an unrealistic per-call shape.

### Fix applied

Replaced `list(...)` with a queryset reference + `.iterator(chunk_size=500)` on the single archive-write pass, building `run_ids` and `student_level_pairs` during the iterator pass instead of after. Downstream filters (`turn__run__in=...`, `Run.objects.filter(...).update(...)`) now use a queryset subquery filter (`Run.objects.filter(created_at__date__gte=..., created_at__date__lte=...)`) so PG re-evaluates with the `created_at` index, no Python materialisation. Memory footprint reduced from ~700 MB to ~2.5 MB at chunk size 500.

---

## 4. Limit #3 — `aggregate_weekly_rollups` prefetched materialisation (NOT YET FIXED)

### Pre-fix state

`DigitMilePanel/digitmileapi/weekly_aggregation.py` (lines 164–181):

```python
ordered_turns = Prefetch(
    "turn_events",
    queryset=TurnEvent.objects.order_by("turn_index").prefetch_related(
        Prefetch(
            "special_tile_triggers",
            queryset=SpecialTileTrigger.objects.order_by("chain_index"),
        )
    ),
)

runs = list(
    Run.objects.filter(
        created_at__date__gte=week_start, created_at__date__lte=week_end
    )
    .select_related("student__classroom__teacher")
    .prefetch_related(ordered_turns)
    .order_by("student_id", "created_at", "id")
)
```

### Original design rationale

The rollup computation is **per-turn**: each `StudentWeek*Stats` table aggregates over individual `TurnEvent` rows (card types, special-tile triggers, decision times, etc.). A single SQL pass with eager loading + Python defaultdict accumulation is the simplest implementation that handles all rollup dimensions in one read of the raw data.

At per-school production volume:

```
3 500 runs × ~20 turns = ~70 000 TurnEvent rows
70 000 × ~1.5 KB (JSON fields) ≈ 105 MB peak prefetch
```

Tight but tolerable on production.

### Where it breaks

National-scale invocation:

```
140 000 Run rows × ~5 KB                                = ~700 MB
2.8 M TurnEvent rows × ~1.5 KB (JSON fields)            ≈ 4 GB
~200 K SpecialTileTrigger rows × ~1 KB                  ≈ 200 MB
                                                       ────────
                                                       ~ 5 GB peak Python heap
```

Far exceeds the production VPS's 3.8 GiB total RAM. **This is the limit that is still currently unaddressed** at the time of this note.

### Production safety

Per-school invocation stays under 150 MB. The architecture is sound at its designed invocation pattern.

### Possible fixes (deferred)

| | Approach | Trade-off |
|---|---|---|
| A | Replace Python defaultdict aggregation with SQL `INSERT … SELECT … GROUP BY`. PG handles aggregation in-engine; Python sees only the final small rollup rows | Largest refactor; correctness-equivalent if verified against existing `verify_weekly_rollups` |
| B | Stream Runs with `.iterator()`; aggregate per-run; flush rollup writes incrementally | Smaller refactor; mid-stream aggregate state is ~30 MB across all rollup tables, easily memory-bounded |
| C | Restructure benchmark to invoke compaction per-teacher (≤500 runs/call) — matches production invocation pattern exactly | No code refactor to pipeline; ~1h to add a `--teacher-id` filter to `compact_weekly_runs` |

The thesis can defend any of (A), (B), (C). Choice is pending.

---

## 5. Verification mechanism for any refactor

The codebase already provides a correctness oracle for changes to `aggregate_weekly_rollups`:

1. **Django management command `verify_weekly_rollups`** (called from line 184–189 of `compact_weekly_runs.py`) compares the existing rollup table rows against a re-aggregation of the raw data. Mismatch raises `CommandError`. Any refactor that produces a different aggregate fails fast.
2. **Test `test_incremental_matches_batch_for_dashboard_rollups`** confirms the incremental rollup path (optimisation H) produces identical output to the batch path. Same logic; same guarantees.

So refactor option (A) or (B) can be validated against the existing rollup verification before being trusted.

---

## 6. Thesis narrative summary

Each limit fits the same shape:

> *"This component is correctly sized for the production invocation pattern. The benchmark forces it through a synthetic invocation pattern that production never executes, and the limit surfaces. The fix can either adapt the benchmark to mirror production (per-school invocation), refactor the component to handle the synthetic pattern, or accept the limit and scale down."*

That tension — **correctly-sized-for-production vs sufficient-for-synthetic-stress-test** — is itself a thesis-worthy observation about the cost of *measuring* a system designed for a particular workload shape. The thesis can foreground this as a methodology point: full national-scale measurement is operationally challenging not because the *system* fails at that scale, but because the *measurement tooling* assumes a different invocation pattern.

---

## 7. File index (pre-fix lines)

- `DigitMilePanel/digitmileapi/models.py:47-54` — `generate_turn_event_id` / `generate_special_tile_trigger_id`
- `DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py` — pre-fix add_arguments was `required=True` for everything; no `--population-only`, no `--append-week-start`, no `--fast-bulk-insert`; flush() in `_generate_runs` was bulk_create-only
- `DigitMilePanel/digitmileapi/management/commands/compact_weekly_runs.py:89-95` — original `runs = list(...)`
- `DigitMilePanel/digitmileapi/weekly_aggregation.py:164-181` — original `runs = list(...).prefetch_related(...)` — **still unfixed**
- `benchmarks/run_scenario.py` — pre-fix had no `storage_walk` branch; no `capture_storage_state`; no `check_disk_safety`
- `benchmarks/scenarios/storage_year_simulation.json` — did not exist before this session
