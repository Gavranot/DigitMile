# Benchmark Load Mathematics Explainer

This document explains the mathematical model used to derive benchmark loads for the DigitMile thesis. It is written as a support document, not as final thesis prose. The goal is to make the assumptions, formulas, and derived RPS values defensible during thesis review.

## 1. Core Idea

The benchmark load should not be chosen arbitrarily. It should be derived from an expected real deployment scenario.

DigitMile is used by pupils during school IT classes. The Unity client does not send telemetry for every turn and does not send periodic heartbeat requests. Instead, the client accumulates all telemetry for one completed game session and sends one HTTP request when the session finishes:

```text
POST /panel/api/runs/ingest/
```

Therefore, ingest load is determined by:

```text
number of completed game sessions per second
```

not by:

```text
number of turns per second
number of pupils currently online
number of individual telemetry events
```

This distinction is crucial. If each turn were sent separately, the benchmark RPS would be much higher. In DigitMile, one completed run produces one ingest request.

## 2. Modeling Levels

The load model has three levels:

| Level | Question | Output |
| ----- | -------- | ------ |
| Population model | How many pupils can be active during the busiest school period? | Peak concurrent users, `CCU` |
| Gameplay model | How often does one active pupil finish a run? | Steady ingest RPS |
| Burst model | What happens when many pupils finish near the school bell? | Short burst RPS |

The benchmark scenarios are then derived from these values:

| Scenario type | Mathematical source |
| ------------- | ------------------- |
| Sustained ingest benchmark | steady ingest RPS |
| Lesson-bell benchmark | burst ingest RPS |
| Overload recovery benchmark | multiple of steady ingest RPS |
| Mixed dashboard benchmark | steady ingest RPS plus teacher read traffic |

## 3. Symbols and Definitions

### 3.1 Population and adoption

| Symbol | Meaning | Base value |
| ------ | ------- | ---------- |
| `N_pop` | Total grade 4-6 pupil population in the target country | 60,000 |
| `A` | Adoption fraction of schools/pupils using the platform | 0.50 for medium scenario |
| `a` | Attendance rate, i.e. fraction of pupils present on a typical school day | 0.93 |
| `N` | Adopted and present pupils | derived |

Formula:

```text
N = N_pop × A × a
```

For medium adoption:

```text
N = 60,000 × 0.50 × 0.93 = 27,900 pupils
```

### 3.2 Timetable structure

| Symbol | Meaning | Base value |
| ------ | ------- | ---------- |
| `f` | IT sessions per pupil per week | 2 |
| `H` | Total school period slots per week | 30 |
| `C_day` | Clustering factor for busiest day | 1.5 |
| `C_period` | Clustering factor for busiest period within that day | 1.5 |
| `P_IT` | Probability that a shift-active pupil is in an IT class during the busiest period | derived |

The uniform baseline is:

```text
f / H
```

If pupils have 2 IT sessions per week and there are 30 period slots per week:

```text
f / H = 2 / 30 = 0.0667
```

This means that under a perfectly uniform timetable, about 6.67% of pupils would be in IT during any particular period slot.

However, real timetables are not perfectly uniform. Some days and some periods are more likely to contain IT classes. The clustering factors approximate this unevenness:

```text
P_IT = (f / H) × C_day × C_period
```

With the base values:

```text
P_IT = (2 / 30) × 1.5 × 1.5
     = 0.0667 × 2.25
     = 0.15
```

So, during the busiest period, approximately 15% of shift-active adopted pupils are assumed to be in IT class.

### 3.3 School shift and concurrency factors

| Symbol | Meaning | Base value |
| ------ | ------- | ---------- |
| `s_morning` | Fraction of pupils in the active school shift at peak time | 0.60 |
| `B` | Within-window concurrency clustering factor | 1.3 |
| `S` | Safety margin | 1.3 |
| `CCU` | Peak concurrent pupils actively playing | derived |

The morning-shift factor exists because not all pupils are in school at the same time. If 60% of pupils are in the morning shift, only that part of the population contributes to the morning peak.

The clustering factor `B` accounts for uneven overlap inside the play window. Even during the same school period, pupils do not start and finish at exactly uniform times. A value above 1.0 gives extra headroom.

The safety margin `S` is a thesis defensibility factor. It makes the target more conservative by assuming that the estimate may be low.

Formula:

```text
CCU = N × s_morning × P_IT × B × S
```

For medium adoption:

```text
N = 27,900
s_morning = 0.60
P_IT = 0.15
B = 1.3
S = 1.3

CCU = 27,900 × 0.60 × 0.15 × 1.3 × 1.3
    = 27,900 × 0.09 × 1.69
    = 2,511 × 1.69
    ≈ 4,244 concurrent pupils
```

Interpretation:

At medium adoption, the model estimates that approximately 4,200 pupils may be actively playing during the busiest school period.

## 4. Gameplay Timing Model

### 4.1 Run duration

| Symbol | Meaning | Base value |
| ------ | ------- | ---------- |
| `T` | Average number of turns per run | 20 |
| `w` | Average wall-clock seconds per turn | 20 seconds |
| `R` | Average wall-clock duration of one run | derived |

Formula:

```text
R = T × w
```

With the base values:

```text
R = 20 × 20 = 400 seconds
```

This is about 6.7 minutes per run.

### 4.2 Steady ingest RPS

If `CCU` pupils are currently playing and each run takes `R` seconds on average, then runs finish at the rate:

```text
RPS_steady = CCU / R
```

For medium adoption:

```text
RPS_steady = 4,244 / 400
           ≈ 10.6 requests/second
           ≈ 11 requests/second
```

This is the source of the 11 RPS steady-ingest benchmark target.

### 4.3 Why this formula is valid

The formula follows from a simple flow-rate argument.

If there are 4,244 active pupils and each pupil completes one run every 400 seconds on average, then the average completion rate is:

```text
4,244 completed runs / 400 seconds
```

Since each completed run produces exactly one ingest POST:

```text
completed runs per second = ingest requests per second
```

Therefore:

```text
RPS_steady = CCU / R
```

This is analogous to Little's Law in queueing theory, where throughput is related to concurrency and average time in the system:

```text
throughput ≈ concurrency / average duration
```

The thesis does not need to present it as formal queueing theory, but the intuition is the same.

## 5. Lesson-Bell Burst Model

The steady-state model describes normal overlapping gameplay. However, there is a separate peak scenario: many pupils may finish a run near the end of the school period and submit results within a short time window.

This is modeled as a burst.

### 5.1 Burst symbols

| Symbol | Meaning | Base value |
| ------ | ------- | ---------- |
| `f_burst` | Fraction of in-class pupils finishing within the burst window | 0.70 |
| `d_burst` | Duration of burst window | 60 seconds |
| `N_burst` | Number of pupils submitting during the burst | derived |
| `RPS_burst` | Burst ingest requests per second | derived |

Formula:

```text
N_burst = N × s_morning × P_IT × f_burst
```

Then:

```text
RPS_burst = N_burst / d_burst
```

### 5.2 Medium-adoption worked example

```text
N = 27,900
s_morning = 0.60
P_IT = 0.15
f_burst = 0.70
d_burst = 60

N_burst = 27,900 × 0.60 × 0.15 × 0.70
        = 27,900 × 0.063
        = 1,757.7 pupils

RPS_burst = 1,757.7 / 60
          ≈ 29.3 requests/second
          ≈ 29 requests/second
```

This is the source of the medium-adoption lesson-bell burst benchmark.

### 5.3 Why burst RPS can be higher than steady RPS

Steady RPS assumes run completions are spread according to average run duration. Burst RPS assumes many pupils submit in a compressed time interval near the bell.

Both are valid, but they model different regimes:

| Regime | Meaning |
| ------ | ------- |
| Steady RPS | Normal average completion flow during active play |
| Burst RPS | Temporarily synchronized submissions near the end of class |

The system must handle both:

- steady RPS for sustained operation;
- burst RPS for short spikes without HTTP 5xx errors and with Redis buffer recovery.

## 6. Scenario Table

Using the base assumptions:

```text
N_pop = 60,000
a = 0.93
f = 2
H = 30
C_day = 1.5
C_period = 1.5
P_IT = 0.15
s_morning = 0.60
B = 1.3
S = 1.3
T = 20
w = 20
R = 400 seconds
f_burst = 0.70
d_burst = 60 seconds
```

| Adoption | `A` | Present adopted pupils `N` | `CCU` | Steady RPS | Burst RPS |
| -------- | --- | -------------------------- | ----- | ---------- | --------- |
| Low | 25% | 13,950 | 2,122 | 5.3 | 14.6 |
| Medium | 50% | 27,900 | 4,244 | 10.6 ≈ 11 | 29.3 ≈ 29 |
| High | 75% | 41,850 | 6,365 | 15.9 ≈ 16 | 43.9 ≈ 44 |

These are the main benchmark load targets:

```text
medium steady: 11 RPS
medium burst:  29 RPS
high steady:   16 RPS
high burst:    44 RPS
```

## 7. Overload Recovery Target

The overload recovery benchmark is derived from the steady medium-adoption target.

If the normal steady target is:

```text
RPS_steady_medium ≈ 11
```

then the 2x overload condition is:

```text
RPS_overload = 2 × 11 = 22 requests/second
```

The benchmark therefore tests:

```text
normal target: 11 RPS
overload:      22 RPS
recovery:      back to 11 RPS
```

The claim is not that the system must comfortably survive 22 RPS forever. The claim is that after a temporary overload, it should recover when traffic returns to the supported target rate.

This distinction is important in defense:

```text
22 RPS is a deliberate overload condition, not the normal service-level target.
```

## 8. Payload Size and Data Volume

The benchmark also needs to account for payload size, not only request count.

### 8.1 Payload size formula

Let:

| Symbol | Meaning | Base value |
| ------ | ------- | ---------- |
| `K_base` | Fixed metadata and map overhead per run | 1.5 KB |
| `K_turn` | Average payload size per turn | 0.7 KB |
| `T` | Average number of turns | 20 |
| `K_payload` | Payload size per run | derived |

Formula:

```text
K_payload = K_base + K_turn × T
```

With base values:

```text
K_payload = 1.5 + 0.7 × 20
          = 1.5 + 14
          = 15.5 KB
```

### 8.2 Ingress bandwidth

```text
bandwidth_MBps = K_payload × RPS / 1024
```

For medium steady load:

```text
bandwidth_MBps = 15.5 × 10.6 / 1024
               ≈ 0.16 MB/s
```

For medium burst:

```text
bandwidth_MBps = 15.5 × 29.3 / 1024
               ≈ 0.44 MB/s
```

Interpretation:

Network bandwidth is not the main bottleneck. The more important cost is server-side validation, buffering, database writes, indexing, and analytics reads.

### 8.3 TurnEvent write pressure

Each completed run produces approximately `T` turn rows.

The steady run ingest rate is:

```text
RPS_steady = CCU / (T × w)
```

Each run has `T` turns, so the approximate `TurnEvent` insert rate is:

```text
TurnEvents_per_second = RPS_steady × T
```

Substitute:

```text
TurnEvents_per_second = (CCU / (T × w)) × T
                       = CCU / w
```

For medium adoption:

```text
TurnEvents_per_second = 4,244 / 20
                       ≈ 212 turn rows/second
```

This explains why batching is important. The HTTP request rate may be 11 RPS, but the database write path still needs to insert hundreds of turn rows per second, plus special tile trigger rows.

## 9. Mapping Formulas to k6 Scenarios

| Mathematical value | Benchmark use |
| ------------------ | ------------- |
| `RPS_steady ≈ 11` | sustained medium ingest benchmark |
| `RPS_burst ≈ 29` | medium lesson-bell benchmark |
| `RPS_steady_high ≈ 16` | high-adoption sustained benchmark |
| `RPS_burst_high ≈ 44` | high-adoption burst benchmark |
| `2 × 11 = 22` | overload recovery benchmark |
| `T = 20` | benchmark dataset average turns per run |
| `K_payload ≈ 15.5 KB` | approximate network and Redis buffer pressure |

The important point for the thesis:

```text
The benchmark scenarios instantiate the load model.
```

They are not arbitrary stress tests.

## 10. Why Redis Buffering Matches the Load Model

The model has two different traffic shapes:

1. steady flow of completed runs;
2. short synchronized bursts near the bell.

Redis buffering is especially useful for the second shape.

During a burst, incoming HTTP requests can be accepted quickly and placed into Redis. PostgreSQL does not need to absorb the entire spike synchronously. The Flusher drains the buffer in batches after and during the burst.

The benchmark should therefore measure two things:

1. HTTP behavior during the burst:

```text
no 5xx errors
p95 latency below the declared threshold
```

2. Buffer recovery after the burst:

```text
Redis ingest_buffer returns to zero within the allowed drain window
```

This is why the lesson-bell benchmark should not only report HTTP latency. It should also report Redis queue depth and drain time.

## 11. Sensitivity Analysis

The load model contains assumptions. A good defense acknowledges them and shows how changes affect the result.

### 11.1 Adoption rate

Adoption rate scales load linearly.

If adoption doubles, `N`, `CCU`, steady RPS, and burst RPS all roughly double.

```text
N = N_pop × A × a
```

Since `A` appears as a direct multiplier, the result is linear.

### 11.2 Timetable clustering

The largest uncertainty is often timetable clustering:

```text
P_IT = (f / H) × C_day × C_period
```

If IT classes are more concentrated on particular days or periods, peak concurrency increases. If they are spread uniformly, peak concurrency decreases.

This is one of the most important assumptions to defend. The values `C_day = 1.5` and `C_period = 1.5` are not exact measurements; they are conservative modeling factors used to avoid underestimating the busiest period.

### 11.3 Run duration

Run duration affects steady RPS:

```text
RPS_steady = CCU / R
R = T × w
```

Shorter runs produce higher RPS because pupils finish more often.

Longer runs produce lower RPS but larger payloads if they contain more turns.

### 11.4 Burst duration

Burst RPS is very sensitive to the burst drain window:

```text
RPS_burst = N_burst / d_burst
```

If the same number of pupils submit over 30 seconds instead of 60 seconds, burst RPS doubles.

Example for medium adoption:

```text
60-second burst: 1,758 / 60 ≈ 29 RPS
30-second burst: 1,758 / 30 ≈ 59 RPS
```

Therefore, the lesson-bell scenario must clearly state the assumed drain window.

## 12. Common Defense Questions and Answers

### Q1. Why do you use completed runs instead of turns to calculate RPS?

Because the Unity client sends one HTTP ingest request per completed run. Turn data is included inside that payload. Turns affect payload size and database row count, but they do not directly increase HTTP request count.

### Q2. Why is the steady benchmark 11 RPS when there are thousands of active pupils?

Because active pupils do not all finish every second. If approximately 4,244 pupils are active and a run lasts about 400 seconds, then only about 4,244 / 400 ≈ 11 runs finish per second.

### Q3. Why is the burst benchmark higher than the steady benchmark?

Because the burst models synchronized submissions near the end of a class. The same pupils who would normally finish over a wider interval may submit within a 60-second window near the bell.

### Q4. Why include safety factors `B` and `S`?

Because timetable distributions, classroom behavior, and run timing are uncertain. `B` models clustering inside the active play window, and `S` provides an explicit conservative margin so the benchmark target is not based on an overly optimistic average case.

### Q5. Why not benchmark the pessimistic 113 RPS case as the main requirement?

Because the pessimistic case combines multiple worst-case assumptions simultaneously: high adoption, extreme timetable clustering, high burst participation, short burst window, and fast gameplay. It is useful as an upper-bound stress scenario, but not as the central service-level requirement for the target 2 vCPU / 3.8 GiB infrastructure.

### Q6. Is 29 RPS the maximum possible traffic?

No. It is the medium-adoption lesson-bell burst target under the stated assumptions. High adoption gives approximately 44 RPS. More pessimistic clustering or a shorter drain window can produce higher burst values.

### Q7. Why does the overload test use 22 RPS?

Because 22 RPS is 2x the medium steady-state target of 11 RPS. It is designed to test recovery from overload, not to redefine the normal supported load.

### Q8. What happens if average run duration is wrong?

If runs are shorter, steady RPS increases. If runs are longer, steady RPS decreases but payload size may increase if the run has more turns. The model is transparent: update `T` or `w`, recompute `R`, then recompute `RPS_steady`.

### Q9. Why is the dashboard load separate from ingest RPS?

Because dashboard traffic is generated by teachers, not pupils. It has a different access pattern: reads, filters, charts, replay views, and cached analytics. It should be benchmarked together with ingest for mixed-load scenarios, but it is not part of the pupil-run completion formula.

### Q10. What is the strongest claim this math supports?

The strongest defensible claim is:

```text
The benchmark loads are derived from an explicit national-adoption usage model, not chosen arbitrarily. The system is evaluated against steady, burst, and overload regimes that correspond to realistic school usage patterns.
```

## 13. Recommended Thesis Placement

The math should appear before the functional and non-functional requirements, or at least before the NFR table.

Recommended structure:

```text
2.1 Context of the existing Unity game
2.2 Expected load model
2.3 Functional requirements
2.4 Non-functional requirements
```

Reason:

The non-functional requirements depend on the load model. If the thesis lists 11 RPS, 29 RPS, and 22 RPS before explaining where they came from, the values can look arbitrary.

## 14. Compact Thesis Version

The final thesis does not need all details from this explainer. A compact version could include:

1. one paragraph explaining one completed run equals one ingest request;
2. a table of variables;
3. formulas for `N`, `P_IT`, `CCU`, `R`, `RPS_steady`, and `RPS_burst`;
4. one medium-adoption worked example;
5. one low/medium/high scenario table;
6. a sentence mapping the values to k6 scenarios.

That should be enough for the main text. The longer reasoning in this document can be used for preparation and defense.

