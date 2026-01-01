# Teacher Statistics Dashboard - Implementation Tasks

## Design Principles
- **Modular architecture**: Each visualization as a separate component that can be toggled on/off
- **Color palette**: Match registration forms (#417690, #5a9fb8, #e74c3c, greens for success, yellows for warnings)
- **Weight recent performance**: More recent games have higher weight in calculations
- **Minimum threshold**: 7-8 games required for meaningful statistics
- **Default timeframe**: All-time (with future option for time windows)
- **Grade filtering**: Optional filter by student grade and classroom grade

---

## Phase 1 - Foundation & Most Immediately Useful

### 1.1 Refactor Template Architecture
- [ ] Create modular component structure for visualizations
- [ ] Add global filters section (grade level, classroom, time range placeholder)
- [ ] Update color scheme to match registration forms
- [ ] Create reusable CSS classes for cards, charts, and panels

### 1.2 Top N Students (Adjustable)
- [ ] Add dropdown to select metric (Accuracy, Score, Win Rate, Decision Time, Improvement Rate, Consistency)
- [ ] Add slider/input for N (default 5, max 20)
- [ ] Implement weighted calculations (recent games weighted more)
- [ ] Display as ranked list with student names, metric value, and trend indicator
- [ ] Color-code based on performance level

### 1.3 Bottom N Students (Two Definitions)
- [ ] **Definition A**: Low Accuracy/Score
  - Filter students with overall low metrics
  - Show as ranked list from worst to best
- [ ] **Definition B**: Flat/Negative Learning Curve
  - Calculate learning curve slope for students with 7+ games
  - Exclude high performers with flat curves (>80% accuracy + flat curve = mastered)
  - Show students with stagnant or declining performance
- [ ] Add toggle to switch between definitions
- [ ] Display with contextual explanations

### 1.4 Students Needing Attention Panel
- [x] Identify students with declining performance (negative learning curve)
- [x] Flag students with high wrong_move ratio (>50%)
- [x] Display as alert cards with specific recommendations
- [ ] Add "mark as addressed" functionality (future: requires database field)

### 1.5 Students Ready for Rewards Panel
- [ ] Calculate top improvers (biggest positive learning curve slope)
- [ ] Identify high accuracy students (>90%)
- [ ] Find fastest completers with high accuracy (top 25% speed + >80% accuracy)
- [ ] Show most consistent performers (low score standard deviation + high average)
- [ ] Display as achievement cards with celebration indicators

### 1.6 Grade Level Filtering
- [ ] Add dropdown for student grade filter (optional)
- [ ] Add dropdown for classroom grade filter (optional)
- [ ] Update all metrics to respect active filters
- [ ] Show filter status clearly in UI

---

## Phase 2 - Deeper Analysis

### 2.1 Learning Curves Per Student (Per Level)
- [ ] Check if student has 7+ games for a specific level
- [ ] Calculate metrics over time for that level:
  - Accuracy trend (correct_moves / total_moves)
  - Speed trend (average decision time)
  - Score trend
- [ ] Plot line charts showing progression
- [ ] Add trend line with slope calculation
- [ ] Color-code mastery indicator:
  - Green: Improving (positive slope)
  - Yellow: Plateaued (near-zero slope)
  - Red: Struggling (negative slope)
  - Blue: Mastered (high performance + plateau)

### 2.2 Cross-Level Learning Transfer
- [ ] Allow teacher to select 2+ levels to compare for a student
- [ ] Show side-by-side learning curves
- [ ] Calculate correlation between performance on different levels
- [ ] Highlight knowledge transfer indicators (improvement on Level B after mastering Level A)

### 2.3 Class Comparison - Multi-Metric Radar Chart
- [ ] Select 2-5 classrooms to compare
- [ ] Calculate class averages for:
  - Average Accuracy
  - Average Score
  - Average Win Rate
  - Average Decision Speed
  - Engagement (games per student)
- [ ] Display as radar/spider chart
- [ ] Show both normalized (percentages) and raw values with toggle

### 2.4 Class Comparison - Side-by-Side Bar Charts
- [ ] Allow selecting specific metric for detailed comparison
- [ ] Show bars for each classroom
- [ ] Include both normalized and raw data views
- [ ] Add explanatory text about normalization

### 2.5 Student Head-to-Head Comparison
- [ ] Multi-select dropdown for 2-5 students
- [ ] Radar chart comparing all metrics
- [ ] Line charts showing progression over time
- [ ] Strengths/weaknesses table
- [ ] Highlight areas where students excel or struggle

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
- [ ] Add timestamp to RunStatistics model (future enhancement)
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

**Phase 1 - COMPLETED**
- [x] TASKS.md created
- [x] Template refactored with modular structure
- [x] Color scheme updated
- [x] Top/Bottom N students implemented
- [x] Attention & Rewards panels implemented
- [x] Grade filtering added
- [x] STATISTICS.md documentation created
- [x] Removed "stuck on level" metric (not applicable to game design)

**Phase 2 - Week 3-4**
- [ ] Learning curves per level
- [ ] Cross-level comparison
- [ ] Class comparison visualizations
- [ ] Student head-to-head comparison

**Phase 3 - Week 5+**
- [ ] Difficulty analysis
- [ ] Engagement metrics
- [ ] Progress map
- [ ] Export functionality

---

## Notes
- Add database migration for RunStatistics.created_at timestamp (needed for engagement metrics)
- Consider caching aggregated statistics for performance (Django cache framework)
- Add tests for metric calculations
- Document each visualization component for future developers
