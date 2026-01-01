# Teacher Statistics Dashboard - Metrics Documentation

## Overview
This document explains all metrics, calculations, and visualizations available in the Teacher Statistics Dashboard. Each metric is designed to help teachers understand student performance, identify students who need help, and recognize high achievers.

---

## Core Metrics

### 1. Accuracy Rate
**What it measures:** The quality of a student's decision-making

**Formula:**
```
Accuracy Rate = (Correct Moves / (Correct Moves + Wrong Moves)) × 100
```

**Example:**
- Correct Moves: 15
- Wrong Moves: 5
- Total Moves: 20
- Accuracy Rate = (15 / 20) × 100 = 75%

**Interpretation:**
- **90-100%**: Excellent decision-making, student understands the concepts very well
- **75-89%**: Good performance, minor mistakes
- **60-74%**: Moderate performance, needs some guidance
- **Below 60%**: Struggling, needs significant help

**When to use:** Identifying students who need help with understanding game mechanics or concepts.

---

### 2. Average Score
**What it measures:** Overall performance across all games

**Formula:**
```
Average Score = Sum of all scores / Number of games played
```

**With Recency Weighting:**
```
Weighted Average = Σ(Score_i × Weight_i) / Σ(Weight_i)

Where Weight_i = Position in chronological order (recent games have higher weights)
Example: Game 1 weight = 1, Game 2 weight = 2, Game 3 weight = 3, etc.
```

**Example (Simple Average):**
- Game 1: 100 points
- Game 2: 150 points
- Game 3: 200 points
- Average = (100 + 150 + 200) / 3 = 150 points

**Example (Weighted Average):**
- Game 1: 100 × 1 = 100
- Game 2: 150 × 2 = 300
- Game 3: 200 × 3 = 600
- Weighted Average = (100 + 300 + 600) / (1 + 2 + 3) = 1000 / 6 = 166.67 points

**Interpretation:**
- Higher scores = better performance
- Weighted average emphasizes recent performance (more relevant for current skill level)

**When to use:** Comparing overall student performance, tracking improvement over time.

---

### 3. Win Rate
**What it measures:** How often a student achieves first place (wins the game)

**Formula:**
```
Win Rate = (Number of Wins / Total Games Played) × 100
```

**Example:**
- Total Games: 20
- Wins (place = 1): 8
- Win Rate = (8 / 20) × 100 = 40%

**Interpretation:**
- **Above 50%**: Very competitive, often outperforms peers
- **30-50%**: Competitive, wins fairly often
- **15-30%**: Moderate competitiveness
- **Below 15%**: Rarely wins, may indicate difficulty or slower pace

**When to use:** Identifying competitive students, understanding how students perform relative to their peers.

**Note:** Win rate depends on competition level. A 30% win rate against strong players may be more impressive than 60% against weaker players.

---

### 4. Average Decision Time
**What it measures:** How quickly a student makes decisions (speed of thinking)

**Formula:**
```
Decision Time = Time Elapsed / (Correct Moves + Wrong Moves)
```

**Example:**
- Time Elapsed: 120 seconds
- Correct Moves: 15
- Wrong Moves: 5
- Total Moves: 20
- Decision Time = 120 / 20 = 6 seconds per move

**Interpretation:**
- **Lower time**: Faster decision-making (may indicate mastery or impulsiveness)
- **Higher time**: Slower, more deliberate thinking (may indicate caution or difficulty)

**Important:** Speed should be considered alongside accuracy!
- Fast + High Accuracy = Mastery
- Fast + Low Accuracy = Impulsive/guessing
- Slow + High Accuracy = Careful, thorough
- Slow + Low Accuracy = Struggling

**When to use:** Understanding student problem-solving approach, identifying students who might be overthinking or rushing.

---

### 5. Improvement Rate
**What it measures:** How much a student's performance has improved over time

**Formula:**
```
Improvement Rate = ((Recent Average - Initial Average) / Initial Average) × 100

Where:
- Initial Average = Average of first 5 games
- Recent Average = Average of last 5 games
```

**Example:**
- First 5 games average accuracy: 60%
- Last 5 games average accuracy: 75%
- Improvement Rate = ((75 - 60) / 60) × 100 = 25% improvement

**Interpretation:**
- **Positive value**: Student is improving (good!)
- **Negative value**: Student's performance is declining (needs attention)
- **Near zero**: Performance is stable (could be good if high, concerning if low)

**When to use:** Identifying students making strong progress (for rewards) or those declining (for intervention).

---

### 6. Consistency Score
**What it measures:** How predictable/stable a student's performance is

**Formula:**
```
Consistency Score = 1 - (Standard Deviation / Mean)

Where:
- Standard Deviation measures variability in scores
- Mean is the average score
```

**Example:**
- Scores: [100, 105, 95, 100, 100]
- Mean = 100
- Standard Deviation ≈ 3.54
- Consistency = 1 - (3.54 / 100) = 1 - 0.0354 = 0.9646 ≈ 0.96

**Interpretation:**
- **0.9 - 1.0**: Highly consistent (very predictable performance)
- **0.7 - 0.9**: Moderately consistent
- **Below 0.7**: Highly variable (performance fluctuates significantly)

**What it means:**
- High consistency + High performance = Mastered the material
- High consistency + Low performance = Consistently struggling (needs different approach)
- Low consistency = Unpredictable (may depend on mood, difficulty, or external factors)

**When to use:** Understanding student reliability, identifying students who may need more stable learning environment.

---

## Learning Curve Analysis

### What it measures
How a student's performance changes over repeated attempts at the same level or across multiple levels.

### Calculation Method
Uses **Linear Regression** to find the trend in performance metrics over time.

**Formula:**
```
For a series of performance values [y₁, y₂, y₃, ..., yₙ]:

Slope = (n × Σ(x×y) - Σ(x) × Σ(y)) / (n × Σ(x²) - (Σ(x))²)

Where:
- x = game attempt number (1, 2, 3, ...)
- y = metric value (accuracy, score, etc.)
- n = number of games
```

**Simplified interpretation:**
- Positive slope = Performance improving over time
- Negative slope = Performance declining
- Near-zero slope = Performance stable (plateaued)

### Minimum Data Requirement
**7-8 games** are required for meaningful learning curve analysis because:
- Fewer games may show random variation rather than true trends
- Need enough data points for statistical significance
- Allows identification of consistent patterns

### Trend Classification

**Improving (Slope > 0.05):**
- Student is getting better with practice
- Indicates effective learning
- Should be encouraged to continue

**Declining (Slope < -0.05):**
- Student's performance is getting worse
- May indicate:
  - Burnout or fatigue
  - Increasing difficulty they're not ready for
  - Loss of motivation
- **Needs immediate teacher attention**

**Plateaued (-0.05 ≤ Slope ≤ 0.05):**
- Performance is stable
- Two sub-categories:
  - **Mastered** (high performance + plateaued): Student has learned the material, no further improvement needed
  - **Stuck** (low performance + plateaued): Student isn't improving, needs new teaching approach

### Example Learning Curves

**Example 1: Improving Student**
```
Attempts:  1    2    3    4    5    6    7    8
Accuracy: 50%  55%  60%  65%  70%  75%  80%  85%
Slope: +4.46 (positive, improving)
Status: Student is consistently improving!
```

**Example 2: Mastered**
```
Attempts:  1    2    3    4    5    6    7    8
Accuracy: 92%  90%  93%  91%  92%  94%  91%  93%
Slope: +0.02 (near zero)
Average: 92% (high)
Status: Mastered - consistent high performance
```

**Example 3: Struggling**
```
Attempts:  1    2    3    4    5    6    7    8
Accuracy: 45%  48%  42%  46%  44%  47%  43%  45%
Slope: +0.01 (near zero)
Average: 45% (low)
Status: Stuck - not improving, needs help
```

**Example 4: Declining**
```
Attempts:  1    2    3    4    5    6    7    8
Accuracy: 80%  75%  72%  68%  65%  60%  58%  55%
Slope: -3.57 (negative)
Status: Performance declining - urgent attention needed!
```

---

## Advanced Metrics

### Cross-Level Learning Transfer
**What it measures:** Whether skills learned in one level transfer to another level

**How it works:**
1. Identify levels with similar concepts/mechanics
2. Calculate learning curve slope for Level A
3. Compare initial performance on Level B to final performance on Level A
4. Positive transfer = Student starts Level B better than they started Level A

**Example:**
- Level 1 final accuracy: 85%
- Level 2 initial accuracy: 70%
- Transfer score: 70% (good, but not full transfer)
- If Level 2 initial = 50%: Poor transfer, concepts didn't carry over
- If Level 2 initial = 85%: Excellent transfer!

**Interpretation:**
- High transfer: Student understands underlying concepts (not just memorizing)
- Low transfer: May be relying on level-specific strategies

---

## Panel-Specific Metrics

### Students Needing Attention
Identifies students who may be struggling and need teacher intervention.

**Criteria:**
1. **Declining Performance:**
   - Learning curve slope < -0.05
   - Performance is getting worse over time

2. **High Wrong Move Ratio:**
   - Wrong moves / Total moves > 50%
   - Making more mistakes than correct decisions

**Why this matters:**
Early intervention can prevent students from falling behind or becoming discouraged.

---

### Students Ready for Rewards
Identifies students who deserve recognition for their achievements.

**Criteria:**

1. **Top Improvers:**
   - Learning curve slope > 0.1 (strong positive trend)
   - Biggest improvement rates
   - Shows dedication and hard work

2. **High Accuracy:**
   - Accuracy rate ≥ 90%
   - Exceptional decision-making
   - Deep understanding of concepts

3. **Speed + Accuracy:**
   - Top 25% in decision speed
   - AND accuracy > 80%
   - Shows both mastery and confidence

4. **Consistency:**
   - Consistency score > 0.85
   - AND average score above class median
   - Reliable, stable performance

**Why this matters:**
Recognizing achievements boosts motivation and encourages continued engagement.

---

## Class Comparison Metrics

### Normalized vs Raw Data

**Raw Data:**
Shows actual values (total games, average scores, etc.)
```
Class A: 1000 total games
Class B: 500 total games
```

**Normalized Data:**
Shows percentages or per-student averages for fair comparison
```
Class A: 50 games per student (20 students)
Class B: 50 games per student (10 students)
```

**When to use:**
- **Raw data**: Understanding total engagement, resource allocation
- **Normalized data**: Fair comparison between classes of different sizes

### Multi-Metric Radar Chart
Shows multiple metrics at once for easy comparison:
- Average Accuracy
- Average Score
- Win Rate
- Decision Speed (inverted: faster = better)
- Engagement (games per student)

**Example interpretation:**
- Class with large radar area = Well-rounded high performance
- Class with narrow area = Struggling across multiple metrics
- Uneven shape = Strong in some areas, weak in others

---

## Difficulty Analysis

### Level-by-Level Metrics

**Average Accuracy per Level:**
Identifies which levels are hardest/easiest
```
Level 1: 85% average accuracy (easy)
Level 2: 72% average accuracy (moderate)
Level 3: 45% average accuracy (very difficult!)
```

**Interpretation:**
- If most students struggle with a level (< 60% accuracy), the level may:
  - Need better tutorial/instructions
  - Be too difficult for the current curriculum placement
  - Require prerequisite knowledge that students don't have

**Drop-off Rate:**
Percentage of students who stop playing after a level
```
Drop-off = 1 - (Students completing Level N+1 / Students completing Level N)
```

**Example:**
- 100 students complete Level 1
- 60 students complete Level 2
- Drop-off rate at Level 1 = 1 - (60/100) = 40%

**Interpretation:**
- High drop-off (> 30%) indicates potential issues:
  - Level too frustrating
  - Sudden difficulty spike
  - Loss of motivation

---

## Statistical Confidence & Thresholds

### Minimum Game Requirements

**Why 7-8 games minimum for learning curves?**
- Statistical reliability: Need enough data to distinguish trends from random noise
- Pattern recognition: True learning patterns emerge over multiple attempts
- Outlier mitigation: Single good/bad games won't skew the analysis

**Phased requirements:**
- **3-6 games**: Show basic stats (average, min, max) but no trend analysis
- **7-10 games**: Enable learning curve analysis with caution
- **11+ games**: Highly reliable trend data

### Standard Deviation & Confidence

When we show "consistency" or trend analysis, we're implicitly using standard deviation:

**Low standard deviation (< 10% of mean):**
- Scores: [95, 98, 96, 97, 94]
- Very predictable

**High standard deviation (> 30% of mean):**
- Scores: [50, 90, 60, 95, 40]
- Highly variable, hard to predict

---

## Color Coding System

To match the registration form palette:

### Performance Levels
- **Excellent** (90-100%): `#27ae60` (Green)
- **Good** (75-89%): `#5a9fb8` (Light Blue)
- **Moderate** (60-74%): `#f39c12` (Orange)
- **Struggling** (< 60%): `#e74c3c` (Red)

### Trend Indicators
- **Improving**: `#27ae60` (Green) with ↗ arrow
- **Mastered**: `#417690` (Professional Blue) with ★ icon
- **Plateaued**: `#f39c12` (Orange) with → arrow
- **Declining**: `#e74c3c` (Red) with ↘ arrow

### Status Indicators
- **Needs Attention**: `#e74c3c` (Red) background
- **Ready for Reward**: `#27ae60` (Green) background
- **Neutral/Normal**: `#f8f9fa` (Light Gray) background

---

## Interpretation Guidelines for Teachers

### Quick Decision Matrix

**High Accuracy + Fast Speed:**
→ Student has mastered the material, ready for challenges

**High Accuracy + Slow Speed:**
→ Student understands but needs more practice for fluency

**Low Accuracy + Fast Speed:**
→ Student is rushing/guessing, needs to slow down and think

**Low Accuracy + Slow Speed:**
→ Student is struggling, needs targeted help

### Red Flags to Watch For

1. **Negative learning curve**: Immediate intervention needed
2. **High wrong move ratio (>50%)**: Student needs concept review
3. **Drop in consistency**: Check for external factors (stress, issues at home)
4. **Declining engagement**: Risk of giving up, needs motivation

### Positive Indicators

1. **Positive learning curve**: Student is learning effectively
2. **Improving consistency**: Developing mastery
3. **High accuracy on challenging levels**: Deep understanding
4. **Increasing speed with maintained accuracy**: Building fluency
5. **Cross-level transfer**: Generalizing concepts (excellent!)

---

## Example Scenarios

### Scenario 1: Identifying a Struggling Student
**Student Profile:**
- Accuracy: 45%
- Learning curve: -0.08 (declining)
- Wrong move ratio: 65%
- Shows no improvement over last 7-8 games

**Interpretation:**
This student needs immediate help. They're not improving with practice and making more wrong moves than correct ones. Consider:
- One-on-one tutoring
- Review of prerequisite concepts
- Different teaching approach
- Check for external factors affecting performance

### Scenario 2: Identifying a Star Performer
**Student Profile:**
- Accuracy: 92%
- Learning curve: +0.12 (strong improvement)
- Consistency: 0.91
- Decision time: 3.2 seconds (class average: 6.5s)

**Interpretation:**
This student is excelling! They're accurate, fast, consistent, and still improving. Consider:
- Public recognition/reward
- Peer tutoring opportunity
- More challenging content
- Leadership role in group activities

### Scenario 3: Understanding Class Performance
**Class A vs Class B:**

Class A:
- Average accuracy: 78%
- Engagement: 45 games/student
- Consistency: 0.82

Class B:
- Average accuracy: 68%
- Engagement: 62 games/student
- Consistency: 0.71

**Interpretation:**
Class A performs better despite less engagement - they may be more efficient learners. Class B plays more but with lower accuracy and consistency - may need better guidance or clearer instructions. Both classes are engaged (good!), but teaching approach may need adjustment for Class B.

---

## Future Enhancements

### Planned Metrics (Phase 2+)
- Time-based filtering (last 30 days, last semester, etc.)
- Peer comparison percentiles
- Engagement heatmaps
- Predictive analytics (risk of dropping out)
- Custom metric thresholds per teacher preference

### Planned Visualizations (Phase 3)
- Student progress maps
- Difficulty curves
- Engagement calendars
- Export to PDF reports
- Automated insights with AI suggestions

---

## Technical Notes

### Performance Optimization
- Heavy calculations (learning curves, statistics) are computed in the backend
- Results are cached for 5 minutes to reduce server load
- Use pagination for large student lists (>50 students)

### Data Privacy
- All student data is anonymized in exports
- Only teachers can see their own students' data
- Aggregate class statistics don't identify individual students

### Calculation Libraries
- NumPy for efficient statistical calculations
- Django ORM for database queries
- Chart.js for frontend visualizations

---

## Glossary

**Accuracy Rate**: Percentage of correct moves out of total moves
**Learning Curve**: Pattern of performance change over time
**Slope**: Rate of change in learning curve (positive = improving)
**Consistency**: Measure of performance stability
**Decision Time**: Average time per move
**Win Rate**: Percentage of games won (first place)
**Improvement Rate**: Change in performance from early to recent games
**Standard Deviation**: Measure of variability/spread in data
**Normalized Data**: Data adjusted for fair comparison (e.g., per-student averages)
**Plateau**: When performance stops improving (flat learning curve)
**Transfer**: Applying learned skills from one level to another

---

*Last updated: 2025*
*For questions or suggestions, contact the development team*
