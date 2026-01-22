# Teacher Statistics Dashboard - Implementation Tasks

## Design Principles
- **Modular architecture**: Each visualization as a separate component that can be toggled on/off
- **Color palette**: Match registration forms (#417690, #5a9fb8, #e74c3c, greens for success, yellows for warnings)
- **Weight recent performance**: More recent games have higher weight in calculations
- **Minimum threshold**: 7-8 games required for meaningful statistics
- **Default timeframe**: All-time (with future option for time windows)
- **Grade filtering**: Optional filter by student grade and classroom grade

---

## Current Implementation Status (2026-01-20)
- teacher_statistics_dashboard builds student metrics (accuracy, win rate, weighted avg score, improvement, consistency, learning curve trend) and per-level performance data.
- Template renders filters, quick stats cards, attention/reward panels, top/bottom lists, and a classroom bar chart.
- Phase 2 widgets are present in the template/JS: classroom radar, cross-level transfer panel, per-level learning curves, and student comparison charts (some parts incomplete).
- ENABLED_VISUALIZATIONS exists in `DigitMilePanel/digitmileapi/views.py` and gates major visualization sections.
- RunStatistics timestamps added via `digitmileapi/migrations/0012_runstatistics_created_at_runstatistics_updated_at.py` with backfill migration 0013.

## Next Steps (Immediate)
- Decide whether to filter top improvement to positive values (UI now shows correct sign).

## Known Bugs and Inconsistencies
- None currently tracked; continue validating data quality with production runs.

---

## Phase 1 - Foundation & Most Immediately Useful

### 1.1 Refactor Template Architecture
- [ ] Create modular component structure for visualizations (all major sections gated)
- [ ] Add global filters section (grade/classroom filters exist; no time range placeholder)
- [x] Update color scheme to match registration forms
- [x] Create reusable CSS classes for cards, charts, and panels

### 1.2 Top N Students (Adjustable)
- [ ] Add dropdown to select metric (Accuracy, Score, Win Rate, Decision Time, Improvement Rate, Consistency)
- [ ] Add slider/input for N (default 5, max 20)
- [ ] Implement weighted calculations (recent games weighted more; only weighted avg score exists)
- [x] Display as ranked list with student names, metric value, and trend indicator (accuracy/improvement tabs)
- [x] Color-code based on performance level

### 1.3 Bottom N Students (Two Definitions)
- [ ] **Definition A**: Low Accuracy/Score (accuracy only)
  - Filter students with overall low metrics (score not included)
  - Show as ranked list from worst to best
- [ ] **Definition B**: Flat/Negative Learning Curve
  - Calculate learning curve slope for students with 7+ games
  - Exclude high performers with flat curves (>80% accuracy + flat curve = mastered)
  - Show students with stagnant or declining performance
- [x] Add toggle to switch between definitions
- [x] Display with contextual explanations

### 1.4 Students Needing Attention Panel
- [x] Identify students with declining performance (negative learning curve)
- [x] Flag students with high wrong_move ratio (>50%)
- [x] Display as alert cards with specific recommendations
- [ ] Add "mark as addressed" functionality (future: requires database field)

### 1.5 Students Ready for Rewards Panel
- [ ] Calculate top improvers (biggest positive learning curve slope; currently threshold-based)
- [x] Identify high accuracy students (>90%)
- [ ] Find fastest completers with high accuracy (top 25% speed + >80% accuracy)
- [x] Show most consistent performers (consistency threshold + weighted avg score)
- [x] Display as achievement cards with celebration indicators

### 1.6 Grade Level Filtering
- [x] Add dropdown for student grade filter (optional)
- [ ] Add dropdown for classroom grade filter (optional)
- [x] Update all metrics to respect active filters
- [ ] Show filter status clearly in UI

---

## Phase 2 - Deeper Analysis

### 2.1 Learning Curves Per Student (Per Level)
- [x] Check if student has 7+ games for a specific level
- [x] Calculate metrics over time for that level:
  - Accuracy trend (correct_moves / total_moves)
  - Speed trend (average decision time)
  - Score trend
- [x] Plot line charts showing progression
- [ ] Add trend line with slope calculation (summary only so far)
- [ ] Color-code mastery indicator:
  - Green: Improving (positive slope)
  - Yellow: Plateaued (near-zero slope)
  - Red: Struggling (negative slope)
  - Blue: Mastered (high performance + plateau)

### 2.2 Cross-Level Learning Transfer
- [x] Allow teacher to select 2+ levels to compare for a student
- [ ] Show side-by-side learning curves (current view compares initial vs final)
- [ ] Calculate correlation between performance on different levels
- [ ] Highlight knowledge transfer indicators (current view uses a simple delta)

### 2.3 Class Comparison - Multi-Metric Radar Chart
- [x] Select 2-5 classrooms to compare
- [x] Calculate class averages for:
  - Average Accuracy
  - Average Score
  - Average Win Rate
  - Average Decision Speed
  - Engagement (games per student)
- [x] Display as radar/spider chart
- [x] Show both normalized (percentages) and raw values with toggle

### 2.4 Class Comparison - Side-by-Side Bar Charts
- [ ] Allow selecting specific metric for detailed comparison
- [x] Show bars for each classroom (avg score + win rate only)
- [ ] Include both normalized and raw data views
- [ ] Add explanatory text about normalization

### 2.5 Student Head-to-Head Comparison
- [x] Multi-select dropdown for 2-5 students
- [x] Radar chart comparing all metrics
- [x] Line charts showing progression over time
- [x] Strengths/weaknesses table
- [x] Highlight areas where students excel or struggle

---

## Phase 3 - Advanced Insights

### 3.1 Difficulty Analysis
- [ ] Aggregate data across all students per level
- [ ] Calculate:
  - Average accuracy per level
  - Average completion time per level
  - Win rate per level
  - Drop-off rate (students who stop after this level)
- [ ] Visualize as horizontal bar chart (levels on Y-axis)
- [ ] Flag levels that may need better teaching materials

### 3.2 Engagement Metrics
- [ ] Games played per student over time
- [x] Add timestamp to RunStatistics model (created_at/updated_at in migration 0012)
- [ ] Activity heatmap (calendar view)
- [ ] Peak playing times analysis
- [ ] Completion rate funnel chart

### 3.3 Class Progress Map
- [ ] Create grid visualization
  - Rows: Students
  - Columns: Levels
  - Cells: Performance color code
- [ ] Color coding:
  - Green: Mastered (high accuracy + multiple attempts)
  - Yellow: In Progress (medium accuracy)
  - Red: Struggling (low accuracy)
  - Gray: Not Attempted
- [ ] Make cells clickable to see detailed stats

### 3.4 Export & Reporting
- [ ] Export student data as CSV
- [ ] Generate PDF reports for parent-teacher conferences
- [ ] Create printable progress reports per student
- [ ] Schedule automated weekly summary emails

---

## Component Modularity System

### Visualization Components
Each visualization is a self-contained component that can be toggled:

```python
ENABLED_VISUALIZATIONS = {
    'top_students': True,
    'bottom_students': True,
    'attention_panel': True,
    'rewards_panel': True,
    'learning_curves': True,
    'class_comparison': True,
    'student_comparison': True,
    'difficulty_analysis': False,  # Phase 3
    'engagement_metrics': False,   # Phase 3
    'progress_map': False,         # Phase 3
}
```

### Template Structure
```
- Global filters bar
- Quick stats cards (always visible)
- Modular visualization sections:
  {% if 'top_students' in enabled_viz %}
    <!-- Top Students Component -->
  {% endif %}

  {% if 'attention_panel' in enabled_viz %}
    <!-- Attention Panel Component -->
  {% endif %}
  ...
```

---

## Metrics Calculation Details

### Weighted Recent Performance
- Games in last 30 days: weight = 3.0
- Games 31-90 days ago: weight = 2.0
- Games 91-180 days ago: weight = 1.5
- Games 180+ days ago: weight = 1.0

### Learning Curve Slope Calculation
For students with 7+ games on a level:
1. Sort games chronologically
2. Calculate metric for each game (accuracy, speed, or score)
3. Use linear regression to find slope
4. Classify:
   - Slope > 0.05: Improving
   - Slope < -0.05: Declining
   - -0.05 ≤ Slope ≤ 0.05: Plateaued
   - Plateaued + High Performance (>80% accuracy): Mastered

### Consistency Score
`consistency = 1 - (std_dev(scores) / mean(scores))`
- 1.0 = perfectly consistent
- < 0.7 = highly variable

---

## Implementation Checklist

**Phase 1 - In progress**
- [x] TASKS.md maintained
- [x] Filters bar + base styling
- [x] Top/bottom lists + attention/reward panels (fixed N)
- [x] Modular gating fully consistent with ENABLED_VISUALIZATIONS
- [ ] Adjustable Top/Bottom N with metric selector
- [ ] Grade/classroom filter parity and UI status
- [ ] Recency weighting based on timestamps

**Phase 2 - Partially implemented**
- [x] Classroom radar comparison UI (normalized/raw toggle)
- [x] Student head-to-head comparison UI
- [ ] Learning curves per level (score/time charts + trend display)
- [ ] Cross-level transfer analysis (curves + correlation)
- [ ] Classroom bar chart metric selector/normalized view

**Phase 3 - Not started**
- [ ] Difficulty analysis
- [ ] Engagement metrics beyond timestamps
- [ ] Progress map
- [ ] Export functionality

---

## Notes
- RunStatistics created_at/updated_at added in migration 0012; backfill if historical ordering matters.
- Consider caching aggregated statistics for performance (Django cache framework)
- Add tests for metric calculations
- Document each visualization component for future developers
