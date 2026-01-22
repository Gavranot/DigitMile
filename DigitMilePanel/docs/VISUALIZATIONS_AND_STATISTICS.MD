# Visualizations and Statistics Guide

This document explains how the teacher statistics dashboard works, what each visualization communicates, and the exact calculations used. It is intended for developers and administrators who need implementation-level detail and interpretable examples.

## Overview
- The dashboard is rendered by `teacher_statistics_dashboard` in `DigitMilePanel/digitmileapi/views.py` and the template `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`.
- Data is derived from `RunStatistics` rows per student, ordered by `created_at` (fallback to `id`).
- All metrics respect the active filters (student grade and optional classroom filter).
- Minimum attempt thresholds are enforced for trend-based visuals to reduce noise.

## Data Inputs and Filters

### Primary Data Source
- `RunStatistics` records, per student, provide:
  - `score`, `correct_moves`, `wrong_moves`, `time_elapsed`, `player_won`, `place`, `level`.
  - `created_at` is used for chronological ordering and recency weighting.

### Filters
- **Student grade**: limits the student set and classroom aggregates.
- **Classroom**: limits students and classroom stats to a single classroom.

### Minimum Attempts
- Learning curve trends: 7+ valid accuracy points.
- Cross-level transfer: 7+ attempts per level.
- Improvement rate: 7+ valid accuracy points (uses a dynamic window for early datasets).

## Core Metrics and Formulas

### Accuracy
- **Definition**: Percentage of correct moves out of total moves.
- **Formula**: `accuracy = correct_moves / (correct_moves + wrong_moves) * 100`.
- **Meaning**: Higher accuracy indicates better correctness in gameplay decisions.

### Win Rate
- **Definition**: Percent of games where the student achieved first place.
- **Formula**: `win_rate = wins / total_runs * 100`.

### Average Score (Weighted)
- **Definition**: Weighted average of scores using time-based buckets.
- **Weights**:
  - 0–30 days ago: 3.0
  - 31–90 days ago: 2.0
  - 91–180 days ago: 1.5
  - 180+ days ago: 1.0
- **Formula**: `weighted_avg = sum(score_i * weight_i) / sum(weight_i)`.
- **Meaning**: Recent games have stronger influence, highlighting current performance.

### Average Decision Time
- **Definition**: Average time per move, across all games.
- **Formula**: `avg_decision_time = total_time_elapsed / (total_correct + total_wrong)`.
- **Meaning**: Lower values represent faster decision-making.

### Improvement Rate
- **Definition**: Percent change from early games to recent games in accuracy.
- **Method**:
  - Uses a dynamic sample size: `sample_size = min(5, max(3, len(accuracy_values) // 2))`.
  - Compares first `sample_size` accuracy values to last `sample_size` values.
- **Formula**: `improvement_rate = ((recent_avg - initial_avg) / initial_avg) * 100`.

### Consistency Score
- **Definition**: A normalized stability score based on score variance.
- **Formula**: `consistency = 1 - (std_dev(scores) / mean(scores))`.
- **Range**: Clamped to 0–1. Higher means more consistent performance.

### Learning Curve Slope and Trend
- **Definition**: Slope of accuracy over time using linear regression.
- **Thresholds**:
  - `slope > 0.05` → Improving
  - `slope < -0.05` → Declining
  - `-0.05 <= slope <= 0.05` → Plateaued
  - Plateaued + high average accuracy (>80%) → Mastered

## Visualization Guide

### Quick Stats Cards
- **Displays**: total students, total games, average accuracy, average score.
- **Interpretation**: Provides a top-level snapshot of class activity and overall performance.

### Students Needing Attention Panel
- **Criteria**:
  - Learning curve trend is declining, or
  - Wrong-move ratio > 50%.
- **What it tells teachers**: highlights students who may require intervention.

### Students Ready for Rewards Panel
- **Criteria**:
  - Strong improvement (improving trend + slope > 0.1), or
  - Accuracy >= 90%, or
  - Consistency > 0.85 with a positive weighted score.
- **What it tells teachers**: identifies students ready for recognition.

### Top Performing Students
- **By Accuracy**: ranks students by overall accuracy.
- **By Improvement**: ranks students by improvement rate.
- **What it tells teachers**: who is excelling and who is progressing fastest.

### Students Who May Need Help
- **Low Accuracy tab**: bottom accuracy ranking.
- **Flat/Declining Curve tab**: students with negative or flat trends and accuracy < 80%.
- **What it tells teachers**: who is struggling and who is not progressing.

### Classroom Performance Comparison (Bar Chart)
- **Metrics**: average score and win rate per classroom.
- **What it tells teachers**: classroom-level performance differences.

### Multi-Classroom Radar Comparison
- **Metrics**:
  - Accuracy, average score, win rate, decision speed (inverted), engagement.
- **Modes**:
  - Normalized per-student view.
  - Raw totals view.
- **What it tells teachers**: which classrooms outperform across multiple dimensions.

### Cross-Level Learning Transfer
- **Compares**: initial vs final accuracy between two levels for the same student.
- **What it tells teachers**: whether skills transfer from one level to another.

### Student Learning Curves by Level
- **Charts**: accuracy, score, time elapsed per attempt for the selected level.
- **Summary**: trend label, slope, and attempt count.
- **What it tells teachers**: how a student is learning within a specific level.

### Student Head-to-Head Comparison
- **Radar chart**: compares key metrics across students.
- **Progression charts**: accuracy, score, and decision speed over time.
- **Strengths table**: highlights best values per metric.
- **What it tells teachers**: strengths and weaknesses in a peer comparison.

## Examples

### Example: Student Accuracy and Improvement
- Runs: 10 attempts
- Early accuracy average: 55%
- Recent accuracy average: 70%
- Improvement rate: `(70 - 55) / 55 * 100 = 27.27%`
- Interpretation: strong improvement, may qualify for rewards if trend is improving.

### Example: Weighted Average Score
- Scores: 400 (10 days ago), 350 (50 days ago), 300 (200 days ago)
- Weights: 3.0, 2.0, 1.0
- Weighted average: `(400*3 + 350*2 + 300*1) / (3+2+1) = 350`

## Implementation Notes
- `student_data_json` provides per-student arrays including `accuracy_per_game`, `scores`, `times`, and level-based stats.
- `classroom_stats_json` provides per-classroom aggregates used in bar and radar charts.
- Most charts accept nulls in datasets so missing values do not crash rendering.

## Known Limitations
- Improvements are computed from accuracy only; score-based improvement is not implemented.
- Recency weighting depends on `created_at`; historical runs without timestamps default to uniform weighting if missing.
- Trendlines are summarized by slope values but not drawn on charts yet.

## Future Extensions
- Engagement and activity timelines once full timestamp history is available.
- Exportable summaries for classroom and student performance.
