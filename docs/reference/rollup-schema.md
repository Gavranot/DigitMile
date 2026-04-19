# Weekly Rollup and Replay Archive Schema Spec

Last updated: 2026-03-10

## Why this document exists

This document turns the refactor PRD into a concrete schema and data-flow proposal. It defines the recommended storage grains, key fields, constraints, and how current analytics should map onto those tables.

The design assumes:

- `Run` remains permanent in PostgreSQL,
- `TurnEvent` and `SpecialTileTrigger` become hot-window tables,
- historical replay is served from compressed per-run archives on disk,
- historical analytics are served from weekly rollups.

## Design principles

- rollups store sufficient statistics, not only final rates,
- rollups are normalized by purpose and grain,
- every rollup row must be mergeable across weeks,
- replay archive metadata is relational even if replay bytes live on disk,
- compaction state must be explicit and resumable.

## Implementation progress

Implemented so far:

- `ReplayArchive`
- `WeeklyCompactionRun`
- `StudentWeekStats`
- `StudentWeekLevelStats`
- `StudentWeekHotspotStats`
- `StudentWeekSpecialTileStats`
- `StudentWeekChainLengthStats`
- `StudentWeekCardFamilyStats`
- `StudentWeekConditionalStats`
- `StudentWeekBackCardUsageStats`
- `StudentWeekForeachContextStats`
- `StudentWeekNumberChoiceStats`
- `StudentWeekCardTypeStats`
- `StudentRunBucketTrend`
- `ClassroomWeekStats`
- `Run.raw_data_compacted_at`

Implemented service and command layer pieces:

- replay archive read/write/verify helpers,
- weekly rollup aggregation writer,
- weekly compaction management command,
- archive-only management commands,
- weekly rebuild and verification commands,
- benchmark management command for teacher analytics helpers,
- initial read-path cutover for compacted replay and historical analytics and turn-insight charts,
- canonical `/panel/api/runs/ingest/` Unity-parity normalization and idempotent replay-safe ingest behavior,
- closed-week recording-window policy helper and ingest-path rejection handling,
- card-type decision-time clipping and rollup-backed historical card-type analytics,
- deterministic run-bucket trend building and mixed historical-plus-hot learning-curve reads,
- extended compaction verification for archives, card-type totals, number-choice totals, conditional totals, and optional run-bucket coverage,
- benchmark dataset preparation, Dockerized k6 scenario execution, and operator runbook coverage.

Still pending for full rollout:

- complete historical read cutover for every existing analytics helper,
- richer rebuild/reconciliation commands,
- additional summary tables only if profiling proves they are needed,
- optional Redis caching only if benchmark evidence proves it is worth the operational cost.

## Canonical week boundaries

The system needs one global week definition.

Recommended rule:

- store `week_start` as a date representing the Monday of the target week in server timezone
- derive `week_end` as `week_start + 6 days`

All weekly rollups and compaction records should key off `week_start`.

## Replay archive metadata

Recommended new model: `ReplayArchive`

Purpose:

- store archive lifecycle metadata separately from `Run`
- keep replay lookup explicit and versionable

Suggested fields:

- `id`
- `run` - one-to-one with `Run`
- `archive_status` - `PENDING`, `READY`, `FAILED`, `MISSING`, `CORRUPT`
- `archive_format` - default `json.gz`
- `archive_schema_version`
- `storage_path`
- `compressed_size_bytes`
- `uncompressed_size_bytes`
- `checksum_sha256`
- `archived_at`
- `verified_at`
- `verification_error`

Constraints and indexes:

- unique on `run`
- index on `archive_status`
- index on `archived_at`

Notes:

- if the team prefers fewer joins, the same fields can live directly on `Run`
- a dedicated model is cleaner for future archive migrations or re-archival

## Weekly compaction state

Recommended new model: `WeeklyCompactionRun`

Purpose:

- track lifecycle of aggregation, archival, verification, and deletion for one week
- support retries and diagnostics

Suggested fields:

- `id`
- `week_start`
- `week_end`
- `status` - `PENDING`, `AGGREGATED`, `ARCHIVED`, `VERIFIED`, `COMPACTED`, `FAILED`
- `started_at`
- `completed_at`
- `run_count`
- `turn_count`
- `trigger_count`
- `archive_runs_written`
- `archive_runs_verified`
- `turn_rows_deleted`
- `trigger_rows_deleted`
- `archive_bytes_written`
- `notes`

Constraints and indexes:

- unique on `week_start`
- index on `status`

## Core weekly rollup tables

## 1. `StudentWeekStats`

Purpose:

- primary semester merge unit for student-level dashboard summaries

Grain:

- one row per `student + week_start`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `runs`
- `wins`
- `correct_moves`
- `wrong_moves`
- `score_sum`
- `score_count`
- `score_sum_sq`
- `score_min`
- `score_max`
- `elapsed_sum_ms`
- `elapsed_count`
- `elapsed_sum_sq`
- `elapsed_min_ms`
- `elapsed_max_ms`
- `latest_run`
- `latest_run_created_at`
- `first_run_created_at`
- `created_at`
- `updated_at`

Constraints and indexes:

- unique on `(student, week_start)`
- index on `(teacher, week_start)`
- index on `(classroom, week_start)`

Derived semester metrics supported exactly:

- total runs
- wins
- win rate
- accuracy
- average score
- score min and max
- average elapsed time
- elapsed min and max
- score and elapsed standard deviation
- latest run metadata

## 2. `StudentWeekLevelStats`

Purpose:

- support level-aware dashboard and viz metrics

Grain:

- one row per `student + week_start + level`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `runs`
- `wins`
- `correct_moves`
- `wrong_moves`
- `score_sum`
- `score_count`
- `score_sum_sq`
- `score_min`
- `score_max`
- `elapsed_sum_ms`
- `elapsed_count`
- `elapsed_sum_sq`
- `elapsed_min_ms`
- `elapsed_max_ms`
- `latest_run`
- `latest_run_created_at`

Constraints and indexes:

- unique on `(student, week_start, level)`
- index on `(teacher, week_start, level)`
- index on `(classroom, week_start, level)`

Derived exact metrics supported:

- win rate by level
- wrong-move totals by level
- accuracy by level
- score by level
- time distribution by level

## 3. `StudentWeekHotspotStats`

Purpose:

- preserve mistake hotspots without raw historical wrong-turn rows

Grain:

- one row per `student + week_start + level + tile_before_index`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `tile_before_index`
- `mistake_count`

Constraints and indexes:

- unique on `(student, week_start, level, tile_before_index)`
- index on `(teacher, week_start, level)`
- index on `(classroom, week_start, level)`

Derived exact metrics supported:

- `mistake_hotspots_by_level`

## 4. `StudentWeekSpecialTileStats`

Purpose:

- preserve special-tile trigger breakdowns

Grain:

- one row per `student + week_start + level + special_tile_type`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `special_tile_type`
- `trigger_count`

Constraints and indexes:

- unique on `(student, week_start, level, special_tile_type)`

Derived exact metrics supported:

- `special_tile_breakdown`

## 5. `StudentWeekChainLengthStats`

Purpose:

- preserve chain-length distributions per turn without keeping old triggers live

Grain:

- one row per `student + week_start + level + chain_length`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `chain_length`
- `turn_count`

Constraints and indexes:

- unique on `(student, week_start, level, chain_length)`

Derived exact metrics supported:

- `special_tile_chain_length_distribution_by_level`

## 6. `StudentWeekCardFamilyStats`

Purpose:

- preserve card-family usage, accuracy, and decision-time analytics

Grain:

- one row per `student + week_start + level + card_family`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `card_family`
- `offered_count`
- `chosen_count`
- `correct_count`
- `wrong_count`
- `decision_time_sum_ms`
- `decision_time_count`
- `decision_time_sum_sq_ms`
- `decision_time_min_ms`
- `decision_time_max_ms`

Constraints and indexes:

- unique on `(student, week_start, level, card_family)`
- index on `(teacher, week_start, level, card_family)`

Derived exact metrics supported:

- `offer_choice_share_by_family`
- `card_exposure_vs_adoption_by_family`
- `card_accuracy_by_family`
- `card_accuracy_by_family_by_level`
- `decision_time_by_family_by_level`

Approximate or redesign note:

- quartiles and medians are not recoverable exactly from this table alone

## 7. `StudentWeekCardTypeStats`

Purpose:

- preserve exact card-type averages and counts if concrete card-type charts remain important

Grain:

- one row per `student + week_start + level + card_type`

Suggested fields:

- `id`
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

Constraints and indexes:

- unique on `(student, week_start, level, card_type)`

Use only if the concrete card-type chart is still worth supporting historically. Otherwise family-level storage is enough.

## 8. `StudentWeekConditionalStats`

Purpose:

- preserve tile-conditional and bag-conditional accuracy and else-branch rates

Grain:

- one row per `student + week_start + level + conditional_kind + bucket`

Recommended normalized fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `conditional_kind` - `tile` or `bag`
- `bucket_key` - tile type or comparator string
- `total_count`
- `correct_count`
- `else_count`

Constraints and indexes:

- unique on `(student, week_start, level, conditional_kind, bucket_key)`

Examples:

- tile conditional, bucket `4`
- bag conditional, bucket `eq`
- bag conditional, bucket `lt`
- bag conditional, bucket `gt`

Derived exact metrics supported:

- `tile_conditional_accuracy_by_tile_type_by_level`
- `bag_conditional_accuracy_by_comparator_by_level`

## 9. `StudentWeekBackCardUsageStats`

Purpose:

- preserve back-card usage by level and place-before

Grain:

- one row per `student + week_start + level + place_before`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `place_before`
- `count`

Constraints and indexes:

- unique on `(student, week_start, level, place_before)`

Derived exact metrics supported:

- `back_card_usage_by_place`
- `back_card_usage_by_place_by_level`

## 10. `StudentWeekForeachContextStats`

Purpose:

- preserve historical foreach-context usage without reconstructing board context at request time

Grain:

- one row per `student + week_start + level`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `with_opponent_count`
- `without_opponent_count`

Constraints and indexes:

- unique on `(student, week_start, level)`

Derived exact metrics supported:

- `foreach_tile_context_usage`
- `foreach_tile_context_usage_by_level`

## 11. `StudentWeekNumberChoiceStats`

Purpose:

- preserve number-choice usage and number-decision time analytics

Grain:

- one row per `student + week_start + level + chosen_number`

Suggested fields:

- `id`
- `student`
- `classroom`
- `teacher`
- `week_start`
- `level`
- `chosen_number`
- `choice_count`
- `decision_time_sum_ms`
- `decision_time_count`
- `decision_time_sum_sq_ms`
- `decision_time_min_ms`
- `decision_time_max_ms`

Constraints and indexes:

- unique on `(student, week_start, level, chosen_number)`

Derived exact metrics supported:

- `number_choice_distribution_by_level`
- `number_decision_time_by_choice_by_level`

## Classroom rollups

The system has two choices:

- derive classroom history dynamically by summing student-week rows,
- or store dedicated classroom-week rows.

Recommended approach:

- start with dedicated classroom-week summary rows for the dashboard summary panels,
- derive specialized classroom charts by summing student-week specialized tables unless profiling shows a need for dedicated classroom specialized rollups.

## 12. `ClassroomWeekStats`

Purpose:

- speed up classroom summary panels and class comparisons

Grain:

- one row per `classroom + week_start`

Suggested fields:

- `id`
- `classroom`
- `teacher`
- `week_start`
- `student_count`
- `runs`
- `wins`
- `correct_moves`
- `wrong_moves`
- `score_sum`
- `score_count`
- `score_sum_sq`
- `elapsed_sum_ms`
- `elapsed_count`
- `elapsed_sum_sq`

Constraints and indexes:

- unique on `(classroom, week_start)`
- index on `(teacher, week_start)`

Derived exact metrics supported:

- classroom total runs
- classroom win rate
- classroom accuracy
- classroom average score
- classroom average elapsed time
- engagement when combined with `student_count`

## Trend and heuristic support

Some current metrics depend on ordered raw histories. Historical versions should be redefined over weekly points.

Recommended approach:

- compute weekly accuracy from `StudentWeekStats`
- compute weekly score from `score_sum / score_count`
- compute weekly time-per-move from `elapsed_sum_ms / (correct_moves + wrong_moves)`
- fit improvement and slope calculations over the ordered weekly points

This keeps the metrics pedagogically meaningful while decoupling them from raw turn retention.

## Current metric to rollup mapping

## Exact historical metrics

| Current metric | Recommended source |
| --- | --- |
| `win_rate_by_level` | `StudentWeekLevelStats` |
| `avg_score_by_level` | `StudentWeekLevelStats` |
| `wrong_moves_rate_by_level` | `StudentWeekLevelStats` |
| `time_distribution_by_level` | `StudentWeekLevelStats` |
| `mistake_hotspots_by_level` | `StudentWeekHotspotStats` |
| `special_tile_breakdown` | `StudentWeekSpecialTileStats` |
| `special_tile_chain_length_distribution_by_level` | `StudentWeekChainLengthStats` |
| `offer_choice_share_by_family` | `StudentWeekCardFamilyStats` |
| `card_exposure_vs_adoption_by_family` | `StudentWeekCardFamilyStats` |
| `card_accuracy_by_family` | `StudentWeekCardFamilyStats` |
| `card_accuracy_by_family_by_level` | `StudentWeekCardFamilyStats` |
| `decision_time_by_family_by_level` | `StudentWeekCardFamilyStats` |
| `tile_conditional_accuracy_by_tile_type_by_level` | `StudentWeekConditionalStats` |
| `bag_conditional_accuracy_by_comparator_by_level` | `StudentWeekConditionalStats` |
| `back_card_usage_by_place_by_level` | `StudentWeekBackCardUsageStats` |
| `foreach_tile_context_usage_by_level` | `StudentWeekForeachContextStats` |
| `number_choice_distribution_by_level` | `StudentWeekNumberChoiceStats` |
| `number_decision_time_by_choice_by_level` | `StudentWeekNumberChoiceStats` |

## Redefined historical metrics

| Current metric | New source and meaning |
| --- | --- |
| `improvement_rate` | computed from ordered `StudentWeekStats` weekly accuracy points |
| `learning_curve_slope` | weekly regression over ordered weekly accuracy points |
| `learning_curve_trend` | classification based on weekly slope and weekly mean |
| `avg_score` with recency weighting | weighted weekly score based on weekly sufficient statistics |
| attention/reward heuristics | weekly trend variants derived from weekly performance points |

## Hot-window-only or approximate metrics

| Current metric | Recommendation |
| --- | --- |
| `speed_vs_accuracy_scatter` | recent hot-window only, or redesign as weekly scatter |
| exact per-run series arrays | recent hot-window only |
| exact decision-time quartiles by card type | add histogram/sketch table if still needed, otherwise drop to avg/min/max |

## Archive payload schema

Suggested replay archive JSON shape:

```json
{
  "schema_version": 1,
  "archived_at": "2026-03-10T12:00:00Z",
  "run": {
    "run_id": "run_xxx",
    "student_id": "stu_xxx",
    "student_name": "Student Name",
    "classroom_id": "cls_xxx",
    "level": 4,
    "player_won": true,
    "score": 120,
    "place": 1,
    "elapsed_ms": 45000,
    "correct_moves": 12,
    "wrong_moves": 3,
    "created_at": "2026-03-03T10:15:00Z"
  },
  "game_map": [],
  "turns": [],
  "special_triggers": [],
  "checksum": {
    "algorithm": "sha256",
    "value": "..."
  }
}
```

The replay loader should convert this archive directly into the payload shape expected by the current replay template.

## Compaction algorithm notes

For one target week:

1. select all `Run` rows in range
2. build replay archive for each run
3. aggregate run-level facts into `StudentWeekStats` and `StudentWeekLevelStats`
4. aggregate turn-level facts into specialized weekly tables
5. verify archive count and checksums
6. verify aggregate totals reconcile to source rows
7. delete old `SpecialTileTrigger`
8. delete old `TurnEvent`
9. optionally clear `Run.game_map`
10. mark compaction status complete

Every write path should be idempotent so the same week can be reprocessed safely.

## Query strategy after refactor

### Teacher dashboard

Historical teacher dashboard queries should:

- filter student-week or classroom-week rows by teacher and date range
- aggregate via SQL sums/min/max as needed
- compute final derived percentages in Python only after small aggregated result sets are loaded

### Visualization endpoint

Historical chart payloads should:

- query specialized weekly tables directly
- aggregate over the selected time range
- return the same JSON shape the frontend expects where possible

### Replay endpoint

Replay lookup should:

- check teacher authorization against `Run`
- detect whether hot relational turn rows exist
- use relational replay for hot runs
- use `ReplayArchive` for compacted runs

## Validation and reconciliation checks

For a compacted week, the following must hold:

- sum of weekly `runs` equals raw `Run` count for the target week
- sum of weekly `wins` equals raw winning run count
- sum of weekly `correct_moves` and `wrong_moves` equals raw run totals
- sum of card-family `chosen_count` equals raw turn count
- sum of special-tile counts equals raw trigger count
- sum of chain-length buckets equals raw turn count
- all expected archive files exist and pass checksum validation

## Practical simplifications

To keep the first implementation focused:

- keep concrete card-type historical quartiles out of scope unless they are proven necessary
- prefer family-level historical analytics over card-type historical analytics
- keep per-run historical sequence charts limited to the hot window
- compute classroom historical specialized analytics by summing student-week specialized rows before adding separate classroom-specialized tables

## Final recommendation

Start with the following minimum durable schema set:

- `ReplayArchive`
- `WeeklyCompactionRun`
- `StudentWeekStats`
- `StudentWeekLevelStats`
- `StudentWeekHotspotStats`
- `StudentWeekSpecialTileStats`
- `StudentWeekChainLengthStats`
- `StudentWeekCardFamilyStats`
- `StudentWeekConditionalStats`
- `StudentWeekBackCardUsageStats`
- `StudentWeekForeachContextStats`
- `StudentWeekNumberChoiceStats`
- `ClassroomWeekStats`

This set is sufficient to cover almost all current historical teacher analytics while allowing hot relational gameplay tables to be compacted aggressively after archival.
