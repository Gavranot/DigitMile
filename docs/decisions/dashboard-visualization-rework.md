# Teacher Statistics Dashboard - Visualization Rework

## Overview

This document tracks the complete rework of the teacher statistics dashboard to leverage the new granular analytics models (`Run`, `TurnEvent`, `SpecialTileTrigger`) replacing the legacy `RunStatistics` model.

### Data Model Transition

| Old Model | New Models | Key Benefits |
|-----------|------------|--------------|
| `RunStatistics` | `Run` | Client UUID idempotency, map/bot versioning, precise timing (ms) |
| (none) | `TurnEvent` | Per-turn decision timing, card choice data, board position tracking |
| (none) | `SpecialTileTrigger` | Chain effect analysis, skateboard/clown breakdown |

### Migration Strategy

1. **Phase 1**: Implement new visualizations using new models alongside existing views
2. **Phase 2**: Replace existing visualizations to use new models
3. **Phase 3**: Deprecate RunStatistics-based code paths (keep for historical data)

---

## Starter Dashboard (Priority Implementation)

The following 8 visualizations provide the highest value for teachers and should be implemented first.

### 1. Win Rate by Level (Bar Chart)
**Status**: [ ] Not Started

**Data Source**: `Run` model

**Query**:
```python
from digitmileapi.analytics import RunAnalytics
results = RunAnalytics.win_rate_by_level(teacher=teacher)
# Returns: [{'level': 1, 'total_runs': 50, 'wins': 35, 'win_rate': 70.0}, ...]
```

**Visualization**:
- X-axis: Level numbers (1, 2, 3, ...)
- Y-axis: Win rate percentage (0-100%)
- Bar color: Gradient based on rate (red < 50% < yellow < 75% < green)

**Teacher Value**: Quickly identifies which level is too hard or which concept causes drop-off. Great for lesson planning.

**Implementation Notes**:
- Existing `RunAnalytics.win_rate_by_level()` already implemented in `analytics.py:15`
- Add filter for classroom/grade scope
- Consider showing attempt count as tooltip

---

### 2. Accuracy by Level (Bar/Stacked Chart)
**Status**: [ ] Not Started

**Data Source**: `Run` model

**Query**:
```python
results = RunAnalytics.wrong_moves_rate_by_level(teacher=teacher)
# Returns: [{'level': 1, 'total_correct': 200, 'total_wrong': 50, 'wrong_rate': 20.0}, ...]
```

**Visualization**:
- Stacked bar: correct moves (green) + wrong moves (red) per level
- Alternative: accuracy % bar chart similar to win rate

**Teacher Value**: Separates "didn't finish" from "finished but messy". Teachers can see if errors spike when conditionals appear.

**Implementation Notes**:
- Existing `RunAnalytics.wrong_moves_rate_by_level()` in `analytics.py:100`
- Compute accuracy as `100 - wrong_rate`

---

### 3. Time by Level (Box Plot/Distribution)
**Status**: [ ] Not Started

**Data Source**: `Run.elapsed_ms`

**Query**:
```python
from django.db.models import Avg, Min, Max, StdDev
from digitmileapi.models import Run

time_stats = Run.objects.filter(
    student__classroom__teacher=teacher
).values('level').annotate(
    avg_time=Avg('elapsed_ms'),
    min_time=Min('elapsed_ms'),
    max_time=Max('elapsed_ms'),
    std_time=StdDev('elapsed_ms'),
    run_count=Count('id')
).order_by('level')
```

**Visualization**:
- Box plot showing distribution per level (min, Q1, median, Q3, max)
- Alternative: violin plot for density
- Convert ms to seconds for display

**Teacher Value**: Time tracks cognitive load. High time with low accuracy suggests confusion; low time with low accuracy suggests guessing/rushing.

**Implementation Notes**:
- Need to add percentile calculation (Q1, Q3) - either in Python or use Django's Window functions
- Consider filtering outliers (>3 std dev)

---

### 4. Speed vs Accuracy Scatter Plot
**Status**: [ ] Not Started

**Data Source**: `Run` model (per-run data points)

**Query**:
```python
runs = Run.objects.filter(
    student__classroom__teacher=teacher
).select_related('student').values(
    'id', 'student__full_name', 'level', 'elapsed_ms',
    'correct_moves', 'wrong_moves'
)

# Compute accuracy per run
scatter_data = []
for run in runs:
    total_moves = run['correct_moves'] + run['wrong_moves']
    if total_moves > 0:
        accuracy = run['correct_moves'] / total_moves * 100
        scatter_data.append({
            'x': run['elapsed_ms'] / 1000,  # seconds
            'y': accuracy,
            'level': run['level'],
            'student': run['student__full_name']
        })
```

**Visualization**:
- X-axis: elapsed time (seconds)
- Y-axis: accuracy rate (%)
- Color/shape by level
- Quadrant annotations:
  - Top-right: Slow but accurate (careful learners)
  - Top-left: Fast and accurate (mastery)
  - Bottom-right: Slow and inaccurate (struggling)
  - Bottom-left: Fast and inaccurate (guessing/rushing)

**Teacher Value**: Identifies learners who rush, learners who are careful but slow, and learners who are both strong and fast.

**Implementation Notes**:
- Use Chart.js scatter type
- Add click-to-filter by level
- Consider sampling for large datasets (>1000 points)

---

### 5. Student Learning Curve per Level (Line Chart)
**Status**: [x] Partially Implemented (uses RunStatistics)

**Data Source**: `Run` model, ordered by `created_at`

**Query**:
```python
runs = Run.objects.filter(
    student_id=student_id,
    level=level
).order_by('created_at').values(
    'id', 'correct_moves', 'wrong_moves', 'score', 'elapsed_ms', 'created_at'
)

# Calculate per-attempt metrics
attempts = []
for i, run in enumerate(runs):
    total = run['correct_moves'] + run['wrong_moves']
    accuracy = (run['correct_moves'] / total * 100) if total > 0 else 0
    attempts.append({
        'attempt': i + 1,
        'accuracy': accuracy,
        'score': run['score'],
        'time': run['elapsed_ms'] / 1000,
        'date': run['created_at']
    })
```

**Visualization**:
- X-axis: Attempt number (1, 2, 3, ...)
- Y-axis: Metric value (accuracy %, score, or time)
- Multiple series: Accuracy, Score, Time (with dual Y-axis)
- Trend line with slope indicator

**Teacher Value**: The most teacher-relevant question is "Are they learning with practice?" Shows improvement or stagnation.

**Implementation Notes**:
- Current implementation in `teacher_statistics.html:903-994` uses RunStatistics
- Migrate to use `Run` model queries
- Add slope calculation and trend classification (improving/declining/plateaued/mastered)

---

### 6. Mistake Hotspot Heatmap
**Status**: [ ] Not Started

**Data Source**: `TurnEvent` where `was_correct=False`

**Query**:
```python
from django.db.models import Count
from digitmileapi.models import TurnEvent

mistake_hotspots = TurnEvent.objects.filter(
    run__student__classroom__teacher=teacher,
    was_correct=False
).values('tile_before_index', 'run__level').annotate(
    mistake_count=Count('id')
).order_by('run__level', '-mistake_count')

# Group by level for heatmap
level_hotspots = {}
for entry in mistake_hotspots:
    level = entry['run__level']
    if level not in level_hotspots:
        level_hotspots[level] = {}
    level_hotspots[level][entry['tile_before_index']] = entry['mistake_count']
```

**Visualization**:
- Heatmap grid: rows = levels, columns = tile positions (0-99)
- Color intensity: number of mistakes at that position
- Hover: show exact count and position info

**Teacher Value**: "Where do students make mistakes?" is the teacher's most actionable question. Identifies problem areas for targeted instruction.

**Implementation Notes**:
- Map tile indices need to be understood per level (may need map metadata)
- Consider normalizing by total attempts at that position
- Use Canvas or D3.js for efficient heatmap rendering

---

### 7. Special Tile Trigger Breakdown (Stacked Bar)
**Status**: [ ] Not Started

**Data Source**: `SpecialTileTrigger` model

**Query**:
```python
from django.db.models import Count
from digitmileapi.models import SpecialTileTrigger

trigger_breakdown = SpecialTileTrigger.objects.filter(
    turn__run__student__classroom__teacher=teacher
).values('turn__run__level', 'special_tile_type').annotate(
    trigger_count=Count('id')
).order_by('turn__run__level', 'special_tile_type')

# Type 4 = Clown (move backward 4)
# Type 5 = Skateboard (move forward 4)
```

**Visualization**:
- Stacked bar per level
- Green stack: Skateboard triggers (beneficial)
- Red stack: Clown triggers (penalty)
- Show total count and ratio

**Teacher Value**: Shows whether students tend to benefit from boosts (skateboard) or get punished (clown). Indicates strategic awareness.

**Implementation Notes**:
- Filter by student/classroom for drill-down
- Add per-student breakdown option
- Calculate trigger rate per run (triggers / total_runs)

---

### 8. Decision Time by Card Type (Box Plot)
**Status**: [ ] Not Started

**Data Source**: `TurnEvent.card_decision_time_ms` + `TurnEvent.chosen_card`

**Query**:
```python
from digitmileapi.models import TurnEvent

# Requires parsing chosen_card JSON for card type
turns = TurnEvent.objects.filter(
    run__student__classroom__teacher=teacher
).values('chosen_card', 'card_decision_time_ms', 'run__level')

# Group by card type (requires JSON field extraction)
# In PostgreSQL: chosen_card->>'type'
# For Django, may need to annotate or process in Python
```

**Visualization**:
- Box plot per card type (MOVE, CONDITIONAL, etc.)
- Faceted by level if needed
- Show mean and median indicators

**Teacher Value**: Longer decision time on conditionals is expected early; decreasing over time is evidence of learning. Identifies which card types students struggle with.

**Implementation Notes**:
- `chosen_card` is a JSONField - need to parse for type
- Consider using Django's `JSONExtract` if PostgreSQL
- May need to process in Python if JSON structure varies
- Add number decision time analysis for later levels (where `offered_numbers` is non-empty)

---

## Existing Visualizations Migration

The following visualizations exist in the current implementation and need to be migrated to use the new models.

### Quick Stats Cards
**Current**: Uses `RunStatistics` aggregates
**Migration**: Use `Run` aggregates

```python
# Current (views.py:1135-1138)
stats = RunStatistics.objects.filter(student=student).order_by('created_at', 'id')
total_runs = stats.count()
wins = stats.filter(player_won=True).count()

# New
runs = Run.objects.filter(student=student).order_by('created_at')
total_runs = runs.count()
wins = runs.filter(player_won=True).count()
```

**Status**: [ ] Not Started

---

### Students Needing Attention Panel
**Current**: Based on learning curve trend and wrong move ratio from `RunStatistics`
**Migration**: Use `Run` + add `TurnEvent` decision time analysis

**Enhanced criteria with new data**:
- Declining learning curve (existing)
- High wrong move ratio (existing)
- **NEW**: Consistently slow decision times (above class average)
- **NEW**: High clown trigger rate (frequent penalties)

**Status**: [ ] Not Started

---

### Students Ready for Rewards Panel
**Current**: Based on improvement rate, accuracy, consistency from `RunStatistics`
**Migration**: Use `Run` + add `TurnEvent` analysis

**Enhanced criteria with new data**:
- Strong improvement (existing)
- High accuracy (existing)
- Consistent excellence (existing)
- **NEW**: Improving decision speed over time
- **NEW**: High skateboard trigger rate (strategic play)

**Status**: [ ] Not Started

---

### Top/Bottom Student Rankings
**Current**: Uses `RunStatistics` for accuracy and improvement
**Migration**: Use `Run` model

**Status**: [ ] Not Started

---

### Classroom Bar Chart (Score + Win Rate)
**Current**: Uses `RunStatistics` aggregates
**Migration**: Use `Run` aggregates

**Status**: [ ] Not Started

---

### Multi-Classroom Radar Comparison
**Current**: Uses `RunStatistics` for accuracy, score, win rate, decision speed, engagement
**Migration**: Use `Run` + `TurnEvent` for more accurate decision time

**Enhanced metrics**:
- Replace rough decision time calculation with `TurnEvent.card_decision_time_ms` average

**Status**: [ ] Not Started

---

### Student Head-to-Head Comparison
**Current**: Uses `RunStatistics` for all metrics
**Migration**: Use `Run` + `TurnEvent`

**Status**: [ ] Not Started

---

### Cross-Level Learning Transfer
**Current**: Uses `RunStatistics` grouped by level
**Migration**: Use `Run` grouped by level

**Status**: [ ] Not Started

---

### Student Learning Curves by Level
**Current**: Uses `RunStatistics` for per-level progression
**Migration**: Use `Run` for cleaner data + `TurnEvent` for decision time trends

**Status**: [ ] Not Started

---

## Additional Visualizations (Phase 2+)

These visualizations leverage the full power of the new models but are lower priority than the starter dashboard.

### A. Turn-Level Decision Quality

#### Card Choice Distribution (Stacked Bars)
- Metric: % of chosen card types per level (MOVE vs CONDITIONAL vs other)
- Source: `TurnEvent.chosen_card`
- Value: Shows whether student uses new concepts or avoids them

#### "Fast Wrong vs Slow Correct" Quadrant
- X: card decision time
- Y: was_correct (or accuracy %)
- Source: `TurnEvent`
- Value: Separates guessing (fast+wrong) from reasoning (slower+correct)

#### Turn Accuracy Over Run Duration
- Metric: `was_correct` across `turn_index` (0..end)
- Source: `TurnEvent`
- Value: Detects fatigue or late-run confusion

### B. Number Selection Analytics (Later Levels)

#### Number Choice Frequency
- Metric: frequency of `chosen_number` values (1-5) by level/student
- Source: `TurnEvent` where `offered_numbers` is non-empty
- Value: Shows bias toward small/large steps

#### Number Decision Time Distribution
- Metric: `number_decision_time_ms` distribution
- Source: `TurnEvent` where `chosen_number` is not null
- Value: Highlights difficulty with step estimation

#### "Offered vs Chosen" Matrix
- Metric: For each number value, probability it's chosen when offered
- Source: `TurnEvent.offered_numbers` + `TurnEvent.chosen_number`
- Value: Detects systematic preferences

### C. Special Tile Advanced Analytics

#### Average Chain Length per Turn
- Metric: count of `SpecialTileTrigger` per `TurnEvent`
- Source: `SpecialTileTrigger`
- Value: Long chains may indicate strategic play or accidental cascades

#### "After Trigger Outcome" Effect Chart
- Metric: average delta in place after skateboard vs clown triggers
- Source: `SpecialTileTrigger.place_before`, `place_after`
- Value: Measures whether boosts are helping and traps are hurting

#### Special Tile Hotspot Map
- Metric: heatmap of `special_tile_index` frequency
- Source: `SpecialTileTrigger`
- Value: Identifies problem areas on map

### D. Position/Map Diagnostics

#### Tile Landing Distribution
- Metric: frequency of `tile_after_index` per level
- Source: `TurnEvent`
- Value: Shows common paths and choke points

#### Lead/Lag Transition Matrix
- Metric: `place_before` → `place_after` transitions
- Source: `TurnEvent`
- Value: Shows if students gain/lose position from decisions

### E. Engagement & Time Analytics

#### Progress Over Time (Trend Line)
- Metric: rolling average of win rate or accuracy over calendar time
- Source: `Run.created_at`
- Value: Shows class improvement after instruction

#### Activity Heatmap (Calendar View)
- Metric: games played per day
- Source: `Run.created_at`
- Value: Shows engagement patterns

### F. Per-Run Quality Metrics

#### Run Accuracy Rate (Gauge)
- Metric: `correct_moves / (correct_moves + wrong_moves)`
- Source: `Run`
- Value: Stable performance metric, less noisy than score

#### Turns to Finish
- Metric: count of `TurnEvent` per `Run`
- Source: `TurnEvent`
- Value: More turns = inefficiency. Track improvement as turns decrease.

---

## Implementation Checklist

### Phase 1: Starter Dashboard (Priority)
- [ ] 1. Win rate by level bar chart
- [ ] 2. Accuracy by level stacked bar
- [ ] 3. Time by level box plot
- [ ] 4. Speed vs accuracy scatter
- [ ] 5. Student learning curve (migrate from RunStatistics to Run)
- [ ] 6. Mistake hotspot heatmap
- [ ] 7. Special tile trigger breakdown
- [ ] 8. Decision time by card type

### Phase 2: Migration of Existing Features
- [ ] Quick stats cards → Run model
- [ ] Attention panel → Run + TurnEvent
- [ ] Rewards panel → Run + TurnEvent
- [ ] Top/Bottom rankings → Run model
- [ ] Classroom bar chart → Run model
- [ ] Radar comparison → Run + TurnEvent
- [ ] Student comparison → Run + TurnEvent
- [ ] Cross-level transfer → Run model
- [ ] Learning curves → Run model

### Phase 3: Advanced Visualizations
- [ ] Card choice distribution
- [ ] Fast wrong vs slow correct quadrant
- [ ] Turn accuracy over run
- [ ] Number selection analytics
- [ ] Special tile advanced analytics
- [ ] Position/map diagnostics
- [ ] Engagement heatmap
- [ ] Per-run quality gauges

---

## Technical Notes

### Query Optimization

1. **Prefetch Related Objects**:
```python
runs = Run.objects.filter(
    student__classroom__teacher=teacher
).select_related(
    'student', 'student__classroom'
).prefetch_related(
    Prefetch('turn_events', queryset=TurnEvent.objects.order_by('turn_index'))
)
```

2. **Use Aggregation at Database Level**:
```python
# Good - aggregation in database
stats = Run.objects.filter(...).aggregate(
    avg_score=Avg('score'),
    total_runs=Count('id')
)

# Avoid - aggregation in Python
runs = Run.objects.filter(...)
avg_score = sum(r.score for r in runs) / len(runs)  # Slow for large datasets
```

3. **Batch Processing for Charts**:
```python
# For scatter plots with many points, consider pagination or sampling
MAX_POINTS = 1000
runs = Run.objects.filter(...)[:MAX_POINTS]
```

### JSON Field Handling

For `chosen_card` and `offered_cards` JSONFields:

```python
# PostgreSQL-specific JSONExtract
from django.db.models.functions import Cast
from django.db.models import JSONField
from django.contrib.postgres.fields.jsonb import KeyTextTransform

# Extract card type
TurnEvent.objects.annotate(
    card_type=KeyTextTransform('type', 'chosen_card')
).values('card_type').annotate(count=Count('id'))
```

For database-agnostic approach:
```python
# Process in Python (slower but portable)
turns = TurnEvent.objects.filter(...).values('chosen_card', 'card_decision_time_ms')
card_type_times = defaultdict(list)
for turn in turns:
    card_type = turn['chosen_card'].get('type', 'unknown')
    card_type_times[card_type].append(turn['card_decision_time_ms'])
```

### Chart.js Integration

Current template uses Chart.js. Continue using for consistency:

```javascript
// Scatter plot example
new Chart(ctx, {
    type: 'scatter',
    data: {
        datasets: [{
            label: 'Speed vs Accuracy',
            data: scatterData,  // [{x: time, y: accuracy}, ...]
            backgroundColor: 'rgba(65, 118, 144, 0.6)'
        }]
    },
    options: {
        plugins: {
            tooltip: {
                callbacks: {
                    label: (ctx) => `${ctx.raw.student}: ${ctx.raw.y.toFixed(1)}%`
                }
            }
        }
    }
});
```

For heatmaps, consider:
- Chart.js matrix plugin
- D3.js for more control
- Canvas direct drawing for performance

### Analytics Module Extensions

Extend `digitmileapi/analytics.py` with new methods:

```python
class RunAnalytics:
    # ... existing methods ...

    @staticmethod
    def mistake_hotspots_by_level(teacher=None, classroom_id=None):
        """Get mistake locations grouped by level and tile position."""
        pass

    @staticmethod
    def special_tile_breakdown(teacher=None, classroom_id=None):
        """Get skateboard vs clown trigger counts by level."""
        pass

    @staticmethod
    def decision_time_by_card_type(teacher=None, classroom_id=None):
        """Get decision time statistics grouped by card type."""
        pass

    @staticmethod
    def speed_vs_accuracy_scatter(teacher=None, classroom_id=None, limit=1000):
        """Get per-run speed and accuracy data for scatter plot."""
        pass
```

---

## Data Quality Considerations

### Minimum Data Thresholds

- **Learning curve slope**: Require 7+ attempts per level (as per existing implementation)
- **Classroom comparisons**: Require at least 2 classrooms with data
- **Student rankings**: Require at least 3 runs per student
- **Heatmaps**: Require at least 100 turns of data for meaningful patterns

### Handling Missing Data

- `TurnEvent.chosen_number`: null when number selection not applicable (early levels)
- `TurnEvent.number_decision_time_ms`: null when no number selection
- `SpecialTileTrigger`: may have zero records for some runs

### Historical Data

- `RunStatistics` contains historical data not in new models
- Consider: parallel queries to combine old + new data
- Or: mark dashboard as "new data only" with date cutoff

---

## Files to Modify

| File | Changes |
|------|---------|
| `views.py` | Replace `RunStatistics` queries with `Run` queries in `teacher_statistics_dashboard()` |
| `analytics.py` | Add new query methods for starter dashboard |
| `teacher_statistics.html` | Add new chart components, update JS data handling |
| `models.py` | No changes needed (models already exist) |
| `serializers.py` | Add serializers for new analytics endpoints if needed |
| `urls.py` | Add API endpoints for async chart data if needed |

---

## Timeline & Dependencies

### Dependencies
- Unity game must be sending data to `/panel/api/runs/ingest/` (verify with existing data)
- Sufficient `Run`/`TurnEvent` data in database for meaningful visualizations

### Suggested Implementation Order
1. Verify data exists in new models
2. Implement analytics.py extensions
3. Update views.py to use Run model for existing features
4. Add starter dashboard charts one by one
5. Test with real teacher accounts
6. Migrate remaining visualizations

---

## Notes for Future Reference

- `SpecialTileTrigger.special_tile_type`: 4 = Clown (backward), 5 = Skateboard (forward)
- `TurnEvent.tile_before_index` and `tile_after_index`: 0-based, range depends on map
- `Run.elapsed_ms`: total time in milliseconds (divide by 1000 for seconds)
- `TurnEvent.card_decision_time_ms`: time to choose card in ms
- `TurnEvent.number_decision_time_ms`: time to choose number (nullable)
- Card types in `chosen_card` JSON need to be documented (check Unity code for structure)
