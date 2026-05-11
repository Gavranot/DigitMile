# Move-Optimality Metrics — Implementation Plan

> **Status: READY FOR IMPLEMENTATION.** The design is frozen in
> [`optimality-metrics-proposal.md`](./optimality-metrics-proposal.md). This
> document is the execution plan — the concrete tables, functions, file
> paths, tests, and reconciliation checks needed to ship Phases 1 and 2 into
> the existing weekly-rollup pipeline. Phase 3 (bag-aware EV) is scoped but
> intentionally *deferred*; a follow-up doc will expand it.

## 0. Required reading before you start

Read these in order. Do not skip — the aggregation pipeline has strong
invariants (idempotent rebuilds, streaming sufficient statistics, closed-week
recording windows) and the existing rollup-accuracy tests will fail if you
break them.

1. [`AGENTS.md`](../../AGENTS.md) §6, §7, §11 — backend structure, domain
   model, analytics architecture.
2. [`docs/decisions/optimality-metrics-proposal.md`](./optimality-metrics-proposal.md)
   — the design this plan implements.
3. [`docs/reference/rollup-schema.md`](../reference/rollup-schema.md) — the
   canonical schema contract every new rollup must satisfy (sufficient
   statistics, week-mergeability, indexes).
4. [`docs/reference/analytics-and-dashboard.md`](../reference/analytics-and-dashboard.md)
   — how rollup readers feed the dashboard.
5. [`docs/guides/rollup-runbook.md`](../guides/rollup-runbook.md) —
   operational behaviour of compact/rebuild/verify commands you will be
   extending.
6. Source files (in this order):
   - `DigitMilePanel/digitmileapi/models.py`
     (`StudentWeekBase`, `StudentWeekRunStatsBase`, and every
     `StudentWeek*Stats` sibling — copy that pattern exactly).
   - `DigitMilePanel/digitmileapi/weekly_rollups.py`
     (`sample_stddev_from_stats`, `clip_decision_time_ms`, week-boundary
     helpers — reuse, do not reinvent).
   - `DigitMilePanel/digitmileapi/weekly_aggregation.py`
     (`aggregate_weekly_rollups` and its per-turn loop at ~line 254–439 —
     this is the one loop you insert your calculator into).
   - `DigitMilePanel/digitmileapi/rollup_analytics.py`
     (pattern for historical reader functions — follow `offer_choice_share_by_family`
     and `tile_conditional_accuracy_by_tile_type_by_level` for style).
   - `DigitMilePanel/digitmileapi/analytics.py`
     (`parse_card`, `CARD_FAMILY_BY_TYPE`, `load_level_deck`,
     `_extract_turn_card` — all helpers you'll reuse).
   - `DigitMilePanel/digitmileapi/management/commands/rebuild_weekly_rollups.py`,
     `compact_weekly_runs.py`, `verify_weekly_rollups.py` — you will add
     flags and reconciliation checks.
   - `DigitMilePanel/digitmileapi/tests.py` §`WeeklyAggregationTests` and
     `DigitMilePanel/digitmileapi/test_rollup_accuracy.py` — extend, do not
     branch.

## 1. Scope

### In-scope this plan

- **Phase 1 — Dominated-choice rate.** Binary "is there any offered card
  that strictly dominates the chosen one on all deterministic axes." One
  counter per (student, level, family) plus one per (student, level).
- **Phase 2 — Per-turn regret under three objective functions.** For each
  turn, a deterministic forward simulation of every offered card, yielding
  three per-turn regret values: `regret_distance`, `regret_place`,
  `regret_score`. Aggregated as sufficient statistics (Σ, Σ², count, min,
  max) so weekly stddev can be reconstructed with the existing
  `sample_stddev_from_stats` helper.
- A new simulator module `digitmileapi/move_optimality.py` providing a pure
  function `evaluate_turn(turn, run, game_map_lookup)` that both phases
  consume.
- New weekly rollup tables, populated by extending
  `aggregate_weekly_rollups` in `weekly_aggregation.py`.
- New rollup-backed reader functions in `rollup_analytics.py` exposing the
  metrics to the dashboard layer.
- Reconciliation checks in `verify_weekly_rollups` that guarantee the new
  rows are self-consistent and mergeable.
- Test coverage that (a) locks the simulator to known outcomes for every
  card family, (b) locks the per-turn regret calculation for a hand-built
  turn, (c) asserts weekly rollup totals equal raw totals over a seeded
  week.

### Out of scope this plan

- **Phase 3 — Bag-aware expected-value regret.** Requires a probability
  model over remaining bag states and a separate design review. Leave a
  placeholder interface (see §3.3) so Phase 3 can slot in without a second
  migration.
- Dashboard UI changes beyond exposing the new JSON endpoints. A separate
  frontend task will place them on `teacher_statistics.html`.
- Any changes to ingestion or the `TurnEvent` / `Run` schemas. The raw data
  already captures everything we need.

## 2. Data model changes

### 2.1 New rollup tables

Both extend `StudentWeekBase` (same `(student, classroom, teacher,
week_start, created_at, updated_at)` shape as every other weekly rollup).
Add to `DigitMilePanel/digitmileapi/models.py` alongside the existing
`StudentWeek*Stats` classes. Follow the prefixed-ID convention — add two ID
generators at the top of the file.

#### `StudentWeekOptimalityStats`

One row per `(student, week_start, level, card_family)`. This is the
"per-concept" grain that lets teachers see which *card family* a student is
sloppy on, which is the pedagogical payload of the whole feature.

| Field | Type | Purpose |
|---|---|---|
| `id` | `CharField(16)`, prefix `swo_` | Prefixed PK |
| `level` | `IntegerField` | Level bucket |
| `card_family` | `CharField(64)` | Same vocabulary as `StudentWeekCardFamilyStats.card_family` |
| `turn_count` | `PositiveIntegerField` | Turns counted toward this bucket |
| `evaluable_turn_count` | `PositiveIntegerField` | Turns where the simulator produced a value for every offered card (see §3.2 on un-evaluable turns) |
| `dominated_count` | `PositiveIntegerField` | Turns where `∃ dominator ∈ offered_cards \ {chosen}` |
| `regret_distance_sum` | `BigIntegerField` | Σ over evaluable turns |
| `regret_distance_sum_sq` | `BigIntegerField` | Σ² |
| `regret_distance_min` | `IntegerField(null=True)` | min |
| `regret_distance_max` | `IntegerField(null=True)` | max |
| `regret_place_sum` | `BigIntegerField` | Σ (place regret; see §3.2 for sign convention) |
| `regret_place_sum_sq` | `BigIntegerField` | |
| `regret_place_min` | `IntegerField(null=True)` | |
| `regret_place_max` | `IntegerField(null=True)` | |
| `regret_score_sum` | `BigIntegerField` | |
| `regret_score_sum_sq` | `BigIntegerField` | |
| `regret_score_min` | `IntegerField(null=True)` | |
| `regret_score_max` | `IntegerField(null=True)` | |

Constraints and indexes (mirror `StudentWeekCardFamilyStats`):

- `UniqueConstraint(fields=["student", "week_start", "level",
  "card_family"], name="unique_student_week_optimality_stats")`
- `Index(fields=["teacher", "week_start", "level", "card_family"],
  name="swo_tchr_wk_lvl_fam_idx")`
- `Index(fields=["classroom", "week_start", "level"],
  name="swo_clsrm_wk_lvl_idx")`
- `ordering = ["student", "week_start", "level", "card_family"]`

**Why sufficient statistics and not final averages.** Same reason every
other rollup in this codebase uses Σ/Σ²/n: weekly stddevs must reconstruct
across arbitrary week ranges using the existing
`sample_stddev_from_stats(total, total_sq, count)` helper in
`weekly_rollups.py`. Do not store averages or stddevs directly.

**Why both `turn_count` and `evaluable_turn_count`.** `turn_count` matches
`StudentWeekCardFamilyStats.chosen_count` for reconciliation. The simulator
may occasionally return `None` for a card whose offered representation is
malformed or whose tile math hits an edge case (e.g. `foreach_tile` with an
unknown tile type in the map lookup); those turns are excluded from the
three regret Σs but still counted in `turn_count`. `evaluable_turn_count`
is the denominator the reader will use for average regret.

#### `ClassroomWeekOptimalityStats`

One row per `(classroom, week_start)`. Teacher-dashboard summary grain,
mirroring `ClassroomWeekStats`. Same `*_sum / *_sum_sq / *_min / *_max`
columns for the three regrets plus `turn_count`, `evaluable_turn_count`,
`dominated_count`. Omit `card_family` and `level` — the per-family and
per-level splits come from summing `StudentWeekOptimalityStats` rows.

Constraints:

- `UniqueConstraint(fields=["classroom", "week_start"],
  name="unique_classroom_week_optimality_stats")`
- `Index(fields=["teacher", "week_start"], name="cwo_teacher_week_idx")`

### 2.2 Migration

- `python manage.py makemigrations digitmileapi` should produce a single
  migration adding the two tables. Name it
  `NNNN_student_week_optimality_stats.py`.
- The migration **must not backfill** any historical weeks automatically.
  Backfill is an operator action via `rebuild_weekly_rollups` (see §6).
- Run `makemigrations --check` in CI to confirm no other incidental
  migrations are produced.

## 3. The simulator module

### 3.1 File and surface

New file `DigitMilePanel/digitmileapi/move_optimality.py`. **Pure functions
only** — no Django ORM calls, no `print`. Everything it consumes arrives as
arguments so it is trivially unit-testable without DB fixtures.

Public surface:

```python
def evaluate_turn(turn, run_context) -> OptimalityResult:
    """Return dominated flag + per-objective regrets for one TurnEvent."""

def simulate_card(card, board_state) -> CardOutcome | None:
    """Deterministic forward simulation of one card on a board snapshot.
       Returns None if the card cannot be simulated from this state."""
```

Dataclasses (use `dataclasses.dataclass(frozen=True)`):

```python
@dataclass(frozen=True)
class BoardState:
    tile_before_index: int
    tile_before_type: int
    place_before: int
    bot_positions_before: tuple[BotPosition, ...]
    bag_number_before: int
    game_map_lookup: Mapping[int, int]   # tileMapIndex -> tileType
    level: int

@dataclass(frozen=True)
class CardOutcome:
    tile_after_index: int
    place_after: int
    distance_delta: int       # tile_after - tile_before_index, signed
    score_delta: int          # estimate; see §3.2
    side_effect_severity: int # count of special-tile triggers fired; 0 if none
    branch_taken: str         # "then" | "else" | "n/a", for conditional cards
    simulated_via: str        # "deterministic" | "fallback" — diagnostic

@dataclass(frozen=True)
class OptimalityResult:
    evaluable: bool
    dominated: bool
    regret_distance: int | None
    regret_place: int | None
    regret_score: int | None
    chosen_outcome: CardOutcome | None
    best_outcomes: dict[str, CardOutcome]   # keyed by objective name
```

### 3.2 Objective function definitions (LOCK THESE DOWN)

The three objectives are defined here, once, for the whole project. The
reader functions and dashboard must never re-define them.

**`value_distance(outcome) = outcome.distance_delta`**
Signed count of tiles advanced. `Back`-family cards are naturally negative.
The distance objective models a greedy player.

**`value_place(outcome) = -outcome.place_after`**
Lower place number = better rank (1st place is best). Negating makes
"higher value = better" consistent across objectives, so the regret formula
`best − chosen` is uniform.

**`value_score(outcome) = outcome.score_delta`**
Estimated immediate score change from this card. The game's authoritative
scoring is in the Unity client, not the backend. Since we do not own that
rule, use this approximation for the initial ship:

- `+1` per forward tile reached,
- `+5` if the card triggers a `skateboard` special tile (type 5),
- `−5` if it triggers a `clown` special tile (type 4),
- `+10` bonus if the resulting place is `1`.

Put the constants in a module-level `ScoreWeights` dataclass so we can tune
them without editing logic. **Flag in code and in the dashboard copy** that
`regret_score` is a heuristic, not the authoritative game score, so a
reviewer cannot accuse us of circular reasoning ("you're scoring the
student against your own scoring function").

### 3.3 Simulator responsibilities per card family

`simulate_card` must handle every family in `CARD_FAMILY_BY_TYPE` in
`analytics.py:16-25`. Reuse `parse_card` — do not re-parse `chosen_card`
JSON manually.

| Family | Simulation |
|---|---|
| `move` | Advance `then_value` tiles. |
| `back` | Move `then_value` tiles backward. |
| `conditional_tile` | If `tile_before_type == card.tile_type`: advance `then_value`; else advance `else_value`. Record `branch_taken`. |
| `conditional_bag_{eq,lt,gt}` | Compare `bag_number_before` against `card.if_value` using the matching comparator; take `then_value` or `else_value`. Record `branch_taken`. |
| `bagcount` | Advance by `bag_number_before`. |
| `foreach_tile` | Count occurrences of `card.tile_type` in `game_map_lookup`; advance `count * then_value`. For the with-opponent variant already tracked in `StudentWeekForeachContextStats`, multiply by bot overlap — but only if the card definition supports it; otherwise treat as plain foreach. |
| `unknown` | Return `None`. |

**Special-tile chaining.** For the chosen card, we already have the actual
chain in `SpecialTileTrigger`; use that for `chosen_outcome.side_effect_severity`
and `score_delta`. For *unchosen* cards, simulate special-tile effects by
looking up the target tile's `special` field in `game_map_lookup` and
applying `effect_delta_tiles` transitively until a normal tile is reached
or a safety cap (max 8 hops) is hit. Document the cap explicitly.

**Place-after calculation.** Given the simulated `tile_after_index` and the
frozen `bot_positions_before`, compute rank by counting bots whose
`tileMapIndex > tile_after_index`. This is an approximation — in the real
game bots may also move — but it preserves the "regret given current
snapshot" framing from the proposal doc, which is exactly what a student
can reason about at decision time.

**`evaluable = False`** when any of:
- `parse_card` returns `family == "unknown"`,
- a required deterministic field (`then_value`, `tile_before_index`,
  `place_before`) is `None`,
- the simulator hits its 8-hop special-tile safety cap.

### 3.4 Dominance check

After simulating every offered card, the chosen card is `dominated` iff
some *other* simulated offered card `O` satisfies:

```
O.distance_delta >= chosen.distance_delta
AND O.place_after <= chosen.place_after       # lower place = better
AND O.side_effect_severity <= chosen.side_effect_severity
AND (strict inequality on at least one axis)
```

(Keep side-effect severity as a raw count for now. If future data shows
skateboards should count negatively and clowns positively, switch to a
signed severity; but do not over-engineer on day one.)

### 3.5 Phase 3 placeholder

Reserve the interface for bag-aware EV. `evaluate_turn` should accept an
optional `probability_model: Optional[BagPosterior] = None`. When absent,
the simulator ignores it (Phase 1/2 behaviour). When present in a later
phase, the simulator will integrate outcomes over the posterior. This keeps
Phase 3 a drop-in.

## 4. Integration into the weekly aggregation loop

The **only** place that should invoke the simulator is inside
`aggregate_weekly_rollups` in
`DigitMilePanel/digitmileapi/weekly_aggregation.py`, inside the existing
per-turn loop. Do not create a second pass over `TurnEvent`s.

### 4.1 Where to hook in

Inside `aggregate_weekly_rollups` there is already a `for run in runs:` and
inside it a `for turn in run.turn_events.all():` (~line 289). Every
per-turn computation happens there. You will:

1. Before the turn loop, build the `game_map_lookup` via the existing
   `_map_lookup(run.game_map)` helper (already used for foreach context at
   line 287).
2. Inside the turn loop, build a `BoardState` from `turn` + the current
   `bag_number` counter (the loop already tracks this at line 286 and
   updates it at line 439).
3. Call `evaluate_turn(turn, board_state)`. The result is deterministic.
4. Feed the result into two new accumulators, following the existing
   `student_card_families` and `classroom_week` patterns:

```python
student_optimality[(student.id, classroom.id, teacher.id, run.level, family)]
classroom_optimality[(classroom.id, teacher.id)]
```

### 4.2 Defaults and update helpers

Add two default-dict factories next to `_default_student_week_summary`:

```python
def _default_student_week_optimality_summary():
    return {
        "turn_count": 0,
        "evaluable_turn_count": 0,
        "dominated_count": 0,
        "regret_distance_sum": 0,
        "regret_distance_sum_sq": 0,
        "regret_distance_min": None,
        "regret_distance_max": None,
        # repeat for place and score
    }
```

Reuse `_update_summary_stats(target, value, value_prefix)` — it already
updates `_sum`, `_count`, `_sum_sq`, `_min`, `_max` consistently. The
optimality accumulator does not need `_count` per-regret because every
evaluable turn produces all three regrets simultaneously; use
`evaluable_turn_count` as the shared denominator in the reader.

### 4.3 Bulk create

Add a `StudentWeekOptimalityStats.objects.bulk_create([...])` block inside
the `with transaction.atomic():` section at the end of
`aggregate_weekly_rollups`, following the pattern of the existing
`StudentWeekCardFamilyStats.objects.bulk_create` (~line 574-601). Do the
same for `ClassroomWeekOptimalityStats` after `ClassroomWeekStats`.

### 4.4 Idempotency

Add both new tables to `_delete_existing_week_rollups` (~line 120-135) so a
re-run for the same `week_start` replaces instead of duplicating. This is
the invariant every other rollup in this file depends on; the
`rebuild_weekly_rollups` command assumes it.

### 4.5 Return dict

Extend the dict returned at the end of `aggregate_weekly_rollups` with:

```python
"student_week_optimality_rows": len(student_optimality),
"classroom_week_optimality_rows": len(classroom_optimality),
```

So operators can see the new rows in the management-command output just
like the existing counts.

## 5. Rollup readers

New functions in `DigitMilePanel/digitmileapi/rollup_analytics.py`.

### 5.1 `optimality_by_family_by_level(student_ids=None)`

Pattern: follow `card_accuracy_by_family_by_level` (line 272-302). Read
`StudentWeekOptimalityStats`, group by `(level, card_family)`, aggregate
via `Sum`/`Min`/`Max`, return rows of:

```python
{
    "level": ...,
    "family": ...,
    "turn_count": ...,
    "evaluable_turn_count": ...,
    "dominated_rate": dominated_count / turn_count * 100,
    "avg_regret_distance": sum / evaluable_turn_count,
    "stddev_regret_distance": sample_stddev_from_stats(sum, sum_sq, evaluable_turn_count),
    "min_regret_distance": ...,
    "max_regret_distance": ...,
    # repeat for place and score
}
```

Guard every division against a zero denominator exactly like every other
reader in this module.

### 5.2 `optimality_summary(student_ids=None)`

Class-level headline numbers. Sum all `StudentWeekOptimalityStats` for the
scope and return the same averages without the per-family split.
Corresponds to what the dashboard will surface as the single "Judgment
quality" card next to the existing Accuracy card.

### 5.3 `optimality_trend_by_week(student_ids=None)`

Same data, grouped by `week_start`, for plotting the regret trend over
weeks. This is what replaces the accuracy line on the existing learning
curve chart as a parallel metric.

### 5.4 Integration with views / dashboard cache

The viz endpoint at `/panel/teacher/statistics/viz-data/` keys payloads
under `teacher_stats_viz:*` with a 7-day TTL invalidated by
`compact_weekly_runs` and `rebuild_weekly_rollups`
([`AGENTS.md` §11](../../AGENTS.md)). Add a new section key like
`optimality` so the frontend can lazy-load it separately; cache
invalidation already covers it because those commands flush the prefix.

## 6. Management commands

### 6.1 `rebuild_weekly_rollups`

`aggregate_weekly_rollups` already rewrites every rollup table for a given
week, so the rebuild command works automatically — no flag needed for the
new tables. Confirm by reading
`DigitMilePanel/digitmileapi/management/commands/rebuild_weekly_rollups.py:45`
(it calls `aggregate_weekly_rollups(week_start)` and that's it).

The operator workflow for the first rollout is therefore:

```bash
# backfill historical optimality for every compacted week
docker exec digitmile-backend python manage.py rebuild_weekly_rollups \
    YYYY-MM-DD --update-compaction --rebuild-run-buckets
```

Run once per completed week. Document this in
`docs/guides/rollup-runbook.md` under a new "Optimality backfill" section.

### 6.2 `compact_weekly_runs`

`compact_weekly_runs` calls `aggregate_weekly_rollups` internally for the
target week, so it will populate the new rollup rows on every future
weekly compaction with no code change. Verify by reading the command and
tracing through; add an assertion in the command's post-step logging that
the new row counts are non-zero when `turn_count > 0`.

### 6.3 `verify_weekly_rollups`

Add a new verification block following the existing pattern for
card-family totals. For the target week, assert:

- `Σ StudentWeekOptimalityStats.turn_count` equals
  `Σ StudentWeekCardFamilyStats.chosen_count` (both should equal the raw
  `TurnEvent` count for the week — the existing check already verifies the
  card-family side).
- `Σ evaluable_turn_count ≤ turn_count`.
- `dominated_count ≤ evaluable_turn_count`.
- For every `(student, week, level)` with a `StudentWeekCardFamilyStats`
  row, there is a matching `StudentWeekOptimalityStats` row for the same
  key.

Gate the check behind a `--verify-optimality` flag initially (mirroring the
existing `--verify-run-buckets` flag) so operators can opt in during the
rollout period. Once it's proven green, flip the default to on.

## 7. Tests

Add to `DigitMilePanel/digitmileapi/tests.py`. Do **not** create a new test
file — the existing one is organized by feature with shared setup.

### 7.1 `MoveOptimalitySimulatorTests(TestCase)`

Pure-function tests, no DB. Hand-build `BoardState` snapshots and assert
`simulate_card` outcomes for every card family. Minimum coverage:

- `move` positive and zero.
- `back` respecting non-negative resulting tile index.
- `conditional_tile` both branches — `branch_taken` asserted.
- `conditional_bag_eq/lt/gt` both branches at boundary values
  (`bag == threshold`, `bag == threshold-1`, `bag == threshold+1`).
- `bagcount` with `bag_number_before ∈ {1, 6}`.
- `foreach_tile` counting with 0, 1, and N matching tiles in
  `game_map_lookup`.
- Special-tile chain: a crafted map where landing on tile X chains into
  tile Y; assert `side_effect_severity == 2` and the chained
  `tile_after_index`.
- Safety cap: a loop map; assert the simulator returns with
  `simulated_via == "fallback"` or `evaluable=False` instead of spinning.

### 7.2 `MoveOptimalityDominanceTests(TestCase)`

Build an `OptimalityResult` fixture with three offered outcomes and assert:

- Card B strictly dominates card A → `dominated == True`.
- Two cards tied on every axis → `dominated == False`.
- Cards that trade tiles for place (one better on distance, worse on
  place) → `dominated == False`.

### 7.3 `WeeklyOptimalityAggregationTests(WeeklyAggregationTests)`

Extend the existing `WeeklyAggregationTests` class (~line 741). Reuse its
seeded `Run` / `TurnEvent` fixtures — every assertion below runs on top of
the same dataset so reconciliation against existing tables is trivial.

- After `aggregate_weekly_rollups(week_start)`, assert
  `StudentWeekOptimalityStats.objects.count() == StudentWeekCardFamilyStats.objects.count()`
  over the same `(student, level, family)` distinct keys.
- `Σ turn_count == Σ StudentWeekCardFamilyStats.chosen_count`.
- `Σ evaluable_turn_count <= Σ turn_count`.
- `Σ dominated_count` reconstructs from a direct in-test Python-side
  simulation over the fixture turns. (This is the regression harness that
  locks the whole pipeline.)
- Running `aggregate_weekly_rollups` a second time produces the same row
  count and same values (idempotency).

### 7.4 `test_rollup_accuracy.py` extensions

Add optimality totals to the existing reconciliation test in
`DigitMilePanel/digitmileapi/test_rollup_accuracy.py`. The harness already
compares live `analytics.py` queries against rollup-backed queries over the
seeded week; extend it to call the new `optimality_by_family_by_level`
reader and cross-check counts against a fresh in-test simulator pass.

### 7.5 Command invocations

```bash
docker-compose exec backend python manage.py test digitmileapi.tests.MoveOptimalitySimulatorTests
docker-compose exec backend python manage.py test digitmileapi.tests.MoveOptimalityDominanceTests
docker-compose exec backend python manage.py test digitmileapi.tests.WeeklyOptimalityAggregationTests
docker-compose exec backend python manage.py test digitmileapi.test_rollup_accuracy
docker-compose exec backend python manage.py makemigrations --check
```

All five must pass before merge.

## 8. Reconciliation guarantees

For any completed week the following must hold — write these as
`verify_weekly_rollups` assertions (§6.3), not as docstrings:

1. Every `StudentWeekCardFamilyStats` row has a 1:1 matching
   `StudentWeekOptimalityStats` row on `(student, week_start, level,
   card_family)`.
2. `StudentWeekOptimalityStats.turn_count` equals
   `StudentWeekCardFamilyStats.chosen_count` for the same key.
3. `dominated_count ≤ evaluable_turn_count ≤ turn_count`.
4. `regret_*_sum_sq ≥ regret_*_sum² / evaluable_turn_count` (Cauchy–Schwarz
   — a cheap sanity check that catches sign-flip or accumulation bugs).
5. `ClassroomWeekOptimalityStats` sums equal the sum of
   `StudentWeekOptimalityStats` for the same `(classroom, week_start)`.

## 9. Rollout steps (for the operator)

1. Land the migration on staging.
2. `rebuild_weekly_rollups` every compacted week in order, oldest first.
3. Run `verify_weekly_rollups --verify-optimality` on each week; halt on
   first failure.
4. Flip the dashboard viz endpoint to include the new `optimality`
   section.
5. After a week of stable numbers, drop the `--verify-optimality` flag and
   make the check default-on.
6. Only then start Phase 3 (bag-aware EV).

## 10. Open questions to resolve before coding

- **Score weights (§3.2).** Are the numbers in `ScoreWeights` defensible,
  or do we need the game team to confirm the actual in-game scoring rule
  before shipping? If the real rule is cheap to obtain, use it; if not,
  ship the heuristic and document the approximation explicitly.
- **Foreach-tile dependence on bot positions.** The current
  `StudentWeekForeachContextStats` already splits foreach plays by
  `with_opponent_count` / `without_opponent_count`. Confirm whether
  `value_distance` for foreach cards should incorporate bot overlap or
  not — the simulator should match whatever rule the *game* uses to
  resolve the card, not an independent interpretation.
- **Dominance on `side_effect_severity`.** If future play-testing shows
  that triggering *more* special tiles is not strictly worse (skateboards
  are good), we will need to split severity into signed positive and
  negative components. Do not fix this pre-emptively; fix it on the first
  real data point that demands it.
- **Classroom-grain optimality duplication.** We're adding
  `ClassroomWeekOptimalityStats` at the same time as the student-grain
  table. The pattern elsewhere in the codebase starts with student grain
  only and adds classroom grain later if profiling demands. Consider
  deferring `ClassroomWeekOptimalityStats` to a second migration if the
  reviewer wants to minimise first-cut schema surface.

Resolve each of the above in the PR description before requesting review.
