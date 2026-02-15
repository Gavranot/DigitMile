# Run Analytics Models Documentation

This document describes the new analytics data models (`Run`, `TurnEvent`, `SpecialTileTrigger`) that capture granular game data from the Unity client. These models replace the legacy `RunStatistics` model for all new analytics and visualization features.

## Overview

The new analytics system captures detailed per-turn game data, enabling rich visualizations and statistics that were not possible with the legacy `RunStatistics` model.

### Model Hierarchy

```
Run (game session)
 └── TurnEvent (per-turn data, 30-60 per run)
      └── SpecialTileTrigger (special tile chain effects, 0+ per turn)
```

### Location

- **Models**: `digitmileapi/models.py`
- **Serializers**: `digitmileapi/serializers.py`
- **Analytics Helpers**: `digitmileapi/analytics.py`
- **Ingestion Endpoint**: `POST /panel/api/runs/ingest/`

---

## Models

### Run

Represents a single game session (run) for a student. Uses client-provided UUID for idempotent ingestion.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUIDField (PK) | Client-provided UUID for idempotency |
| `student` | ForeignKey(Student) | The student who played this run |
| `level` | IntegerField | Game level (1-based) |
| `player_won` | BooleanField | Whether the student won the game |
| `score` | IntegerField | Final score achieved |
| `elapsed_ms` | IntegerField | Total game duration in milliseconds |
| `correct_moves` | IntegerField | Number of correct card choices |
| `wrong_moves` | IntegerField | Number of incorrect card choices |
| `map_version` | CharField | Version of the game map used |
| `bot_version` | CharField | Version of the AI opponent |
| `rng_seed` | IntegerField (nullable) | Random seed for reproducibility |
| `created_at` | DateTimeField | When the run was ingested |
| `updated_at` | DateTimeField | Last modification timestamp |

**Indexes**:
- `run_student_created_idx` - For filtering runs by student with date ordering
- `run_student_level_idx` - For level-specific student queries
- `run_level_created_idx` - For level-wide analytics

**Related name**: `student.runs`

### TurnEvent

Represents a single turn within a game run. Captures the player's card choice, timing, and resulting board state changes.

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField (PK) | Auto-generated primary key |
| `run` | ForeignKey(Run) | Parent run |
| `turn_index` | IntegerField | Turn number (0-based, sequential) |
| `timestamp_played` | DateTimeField | When this turn was played (UTC) |
| `chosen_card` | JSONField | The card chosen by the player |
| `offered_cards` | JSONField | All cards offered to the player |
| `was_correct` | BooleanField | Whether the choice was correct |
| `tile_before_index` | IntegerField | Player position before turn (0-99) |
| `tile_before_type` | IntegerField | Tile type at position before turn |
| `tile_after_index` | IntegerField | Player position after turn |
| `place_before` | IntegerField | Race position before turn (1-4) |
| `place_after` | IntegerField | Race position after turn (1-4) |
| `card_decision_time_ms` | IntegerField | Time taken to choose card in ms |
| `offered_numbers` | JSONField | Numbers offered for selection (empty if not applicable) |
| `chosen_number` | IntegerField (nullable) | Number chosen (null if not applicable) |
| `number_decision_time_ms` | IntegerField (nullable) | Time to choose number in ms |

**Constraints**:
- `unique_turn_per_run` - Ensures turn_index is unique within a run

**Indexes**:
- `turn_run_index_idx` - For efficient turn ordering
- `turn_run_timestamp_idx` - For time-based queries

**Related name**: `run.turn_events`

### SpecialTileTrigger

Represents a special tile effect triggered during a turn. Multiple triggers can chain from a single turn.

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField (PK) | Auto-generated primary key |
| `turn` | ForeignKey(TurnEvent) | Parent turn event |
| `chain_index` | IntegerField | Order in the chain (0-based) |
| `special_tile_index` | IntegerField | Board position of the special tile |
| `special_tile_type` | IntegerField | Type of special tile (4 or 5) |
| `effect_delta_tiles` | IntegerField | Tiles moved by this effect (-4 or +4) |
| `target_tile_index` | IntegerField | Position after the effect |
| `target_tile_type` | IntegerField | Type of tile landed on |
| `place_before` | IntegerField | Race position before effect |
| `place_after` | IntegerField | Race position after effect |

**Special Tile Types**:
- Type 4: Move backward 4 tiles (`effect_delta_tiles = -4`)
- Type 5: Move forward 4 tiles (`effect_delta_tiles = +4`)

**Constraints**:
- `unique_chain_per_turn` - Ensures chain_index is unique within a turn

**Indexes**:
- `trigger_turn_chain_idx` - For chain ordering
- `trigger_tile_index_idx` - For position-based queries
- `trigger_tile_type_idx` - For type-based aggregations

**Related name**: `turn.special_tile_triggers`

---

## Analytics Module

The `digitmileapi/analytics.py` module provides query helper functions for building dashboards and visualizations.

### RunAnalytics Class

All methods accept optional filtering parameters:
- `teacher` - Filter by teacher (all their classrooms)
- `classroom_id` - Filter by specific classroom
- `student_ids` - Filter by specific student IDs

#### win_rate_by_level()

Calculate win rate aggregated by level.

```python
from digitmileapi.analytics import RunAnalytics

# For all students of a teacher
results = RunAnalytics.win_rate_by_level(teacher=teacher_instance)
# Returns: [{'level': 1, 'total_runs': 50, 'wins': 35, 'win_rate': 70.0}, ...]
```

#### avg_score_by_level()

Calculate average score statistics by level.

```python
results = RunAnalytics.avg_score_by_level(classroom_id=1)
# Returns: [{'level': 1, 'avg_score': 450.5, 'min_score': 100, 'max_score': 800, 'total_runs': 50}, ...]
```

#### avg_card_decision_time_by_level()

Calculate average card decision time by level.

```python
results = RunAnalytics.avg_card_decision_time_by_level(teacher=teacher_instance)
# Returns: [{'run__level': 1, 'avg_decision_time_ms': 3500.0, 'total_turns': 500}, ...]
```

#### wrong_moves_rate_by_level()

Calculate wrong moves rate by level.

```python
results = RunAnalytics.wrong_moves_rate_by_level(student_ids=[1, 2, 3])
# Returns: [{'level': 1, 'total_correct': 200, 'total_wrong': 50, 'total_moves': 250, 'wrong_rate': 20.0}, ...]
```

#### student_performance_summary()

Get comprehensive performance summary for a single student.

```python
summary = RunAnalytics.student_performance_summary(student_id=1)
# Returns: {
#     'total_runs': 25,
#     'wins': 18,
#     'win_rate': 72.0,
#     'avg_score': 425.5,
#     'accuracy': 85.2,
#     'avg_elapsed_ms': 120000,
#     'avg_card_decision_ms': 3200,
#     'avg_number_decision_ms': 1500
# }
```

#### classroom_leaderboard()

Get top students in a classroom by specified metric.

```python
leaders = RunAnalytics.classroom_leaderboard(classroom_id=1, metric='win_rate', limit=10)
# Returns: [
#     {'student_id': 5, 'student_name': 'Alice', 'total_runs': 30, 'win_rate': 90.0, 'avg_score': 550, 'accuracy': 92.0},
#     ...
# ]
```

Supported metrics: `'win_rate'`, `'avg_score'`, `'accuracy'`, `'total_runs'`

---

## Data Ingestion

### Endpoint

`POST /panel/api/runs/ingest/`

### Characteristics

- **Idempotent**: Duplicate `run_id` returns HTTP 200 (safe to retry)
- **Atomic**: All-or-nothing transaction (no partial data on failure)
- **Bulk-optimized**: Uses `bulk_create()` for TurnEvents and SpecialTileTriggers

### Payload Format

```json
{
    "run_id": "550e8400-e29b-41d4-a716-446655440000",
    "student_id": 1,
    "level": 3,
    "player_won": true,
    "score": 450,
    "elapsed_ms": 125000,
    "correct_moves": 8,
    "wrong_moves": 2,
    "map_version": "1.2",
    "bot_version": "2.0",
    "rng_seed": 12345,
    "turn_events": [
        {
            "turn_index": 0,
            "timestamp_played_unix_ms": 1706400000000,
            "chosen_card": {"type": "move", "value": 3},
            "offered_cards": [{"type": "move", "value": 3}, {"type": "move", "value": 5}],
            "was_correct": true,
            "tile_before_index": 0,
            "tile_before_type": 0,
            "tile_after_index": 3,
            "place_before": 4,
            "place_after": 3,
            "card_decision_time_ms": 2500,
            "offered_numbers": [],
            "chosen_number": -1,
            "number_decision_time_ms": -1,
            "special_tile_triggers": []
        }
    ]
}
```

### Sentinel Values

The Unity client uses `-1` as a sentinel for "not applicable" values:
- `chosen_number: -1` is converted to `null`
- `number_decision_time_ms: -1` is converted to `null`

### Validation Rules

1. `student_id` must reference an existing Student
2. `turn_events` indices must be sequential starting from 0
3. `special_tile_triggers` chain indices must be sequential starting from 0
4. `correct_moves + wrong_moves` must equal the number of turn events

### Response Codes

- `201 Created` - Run successfully ingested
- `200 OK` - Run already exists (idempotent response)
- `400 Bad Request` - Validation error (details in response body)

---

## Migration from RunStatistics

### Legacy Model Status

The `RunStatistics` model remains in the codebase for backward compatibility with existing data. However, all new analytics features should use the `Run`, `TurnEvent`, and `SpecialTileTrigger` models.

### Key Differences

| Aspect | RunStatistics (Legacy) | Run + TurnEvent (New) |
|--------|----------------------|----------------------|
| Granularity | Per-game summary | Per-turn detail |
| Decision timing | Not captured | `card_decision_time_ms`, `number_decision_time_ms` |
| Board state | Not captured | `tile_before_index`, `tile_after_index`, etc. |
| Special tiles | Not captured | Full chain tracking via `SpecialTileTrigger` |
| Card data | Not captured | `chosen_card`, `offered_cards` |
| Idempotency | Server-generated ID | Client-provided UUID |

### Migration Strategy

1. **Parallel existence**: Both systems work simultaneously
2. **New Unity clients**: Should use `/panel/api/runs/ingest/`
3. **Legacy Unity clients**: Continue using `/panel/api/insertLevelStatistics/`
4. **Future**: Deprecate `RunStatistics` after validating new system

---

## Usage in Views and Templates

### Querying Runs for a Teacher

```python
from digitmileapi.models import Run

# Get all runs for a teacher's students
runs = Run.objects.filter(
    student__classroom__teacher=request.user.teacher_profile
).select_related('student', 'student__classroom')
```

### Querying with Prefetch for Turn Data

```python
from django.db.models import Prefetch
from digitmileapi.models import Run, TurnEvent

runs = Run.objects.filter(
    student__classroom_id=classroom_id
).prefetch_related(
    Prefetch(
        'turn_events',
        queryset=TurnEvent.objects.order_by('turn_index')
    )
)

for run in runs:
    for turn in run.turn_events.all():
        print(f"Turn {turn.turn_index}: {'Correct' if turn.was_correct else 'Wrong'}")
```

### Aggregating Decision Times

```python
from django.db.models import Avg
from digitmileapi.models import TurnEvent

avg_times = TurnEvent.objects.filter(
    run__student__classroom_id=classroom_id
).aggregate(
    avg_card_time=Avg('card_decision_time_ms'),
    avg_number_time=Avg('number_decision_time_ms')
)
```

---

## Admin Interface

The new models are registered in Django Admin with teacher-scoped visibility:

- **RunAdmin**: Teachers see only runs from their students
- **TurnEventAdmin**: Inline display within runs
- **SpecialTileTriggerAdmin**: Inline display within turn events

Superusers can see all records for audit purposes.

---

## Management Commands

### Seeding Test Data

```bash
# Low volume (development)
docker-compose exec backend python manage.py seed_database --preset low

# Medium volume (staging)
docker-compose exec backend python manage.py seed_database --preset medium

# High volume (load testing)
docker-compose exec backend python manage.py seed_database --preset high
```

### Clearing Data

```bash
docker-compose exec backend python manage.py clear_school_data --yes
```

This clears all `Run`, `TurnEvent`, and `SpecialTileTrigger` records along with other school data.

---

## Performance Considerations

### Indexing Strategy

The models include carefully designed indexes for common query patterns:
- Student + date filtering
- Level-based aggregations
- Turn ordering within runs
- Chain ordering within turns

### Query Optimization

When building visualizations:
1. Use `select_related()` for single FK relationships
2. Use `prefetch_related()` for reverse FK relationships
3. Use `Prefetch` objects to control ordering and filtering
4. Use aggregation functions (`Avg`, `Sum`, `Count`) at the database level

### Bulk Operations

The ingestion endpoint uses `bulk_create()` for efficiency. When creating test data or migrations, follow this pattern:
```python
TurnEvent.objects.bulk_create(turn_events_list)
SpecialTileTrigger.objects.bulk_create(triggers_list)
```

---

## Future Extensions

1. **Real-time analytics**: WebSocket updates for live game tracking
2. **Heatmaps**: Board position analysis using tile index data
3. **Decision pattern analysis**: ML-based analysis of card choice patterns
4. **Replay functionality**: Full game replay using turn-by-turn data
5. **A/B testing**: Compare bot_version and map_version performance
