# Expected Load Model and Derivation of Benchmark Targets

This section is written as thesis-ready source prose in English. It is intended to be translated/adapted into the main thesis section before the functional and non-functional requirements. The purpose of the section is to justify the benchmark loads mathematically, so that the later k6 validation scenarios do not appear arbitrary.

## 2.X Expected Load Model

The non-functional requirements of the DigitMile platform are derived from an explicit model of expected school usage. This is important because the system is not evaluated against arbitrary request rates, but against request rates that follow from the expected number of pupils, the school timetable structure, the gameplay duration, and the way the Unity client sends telemetry to the backend.

The central observation is that the Unity client does not send telemetry continuously during gameplay. It does not send one request per turn, nor does it send periodic heartbeat requests. Instead, the client accumulates the full telemetry of a completed game session locally and sends it as one HTTP request after the run is finished. The load-bearing request is therefore:

```text
POST /panel/api/runs/ingest/
```

This means that the ingest request rate is determined by the number of completed game runs per second. The number of turns in a run affects the payload size and the number of database rows later written by the Flusher process, but it does not directly multiply the number of HTTP requests. This distinction is essential for a correct capacity model. A model based on per-turn submission would significantly overestimate HTTP traffic, while a model based only on the number of registered pupils would ignore the fact that pupils complete runs over time rather than all at the same instant.

For this reason, the benchmark model is built in three steps. First, it estimates how many pupils can be concurrently active during the busiest school period. Second, it estimates how frequently those active pupils complete game runs. Third, it separately models a short burst scenario in which many pupils submit completed runs near the end of a school period.

## 2.X.1 Population and Adoption Model

Let \(N_{pop}\) denote the total population of pupils in grades 4-6 in the target deployment context. The thesis uses:

```text
N_pop = 60,000
```

Not every pupil is assumed to use the platform immediately. Therefore, an adoption factor \(A\) is introduced. For the medium-adoption scenario:

```text
A = 0.50
```

The model also includes an attendance factor \(a\), since not all enrolled pupils are present on a given day:

```text
a = 0.93
```

The number of adopted and present pupils is therefore:

```text
N = N_pop × A × a
```

For the medium-adoption scenario:

```text
N = 60,000 × 0.50 × 0.93
  = 27,900
```

This does not mean that 27,900 pupils are using the platform at the same moment. It means that 27,900 pupils are part of the active reachable population for the modeled scenario. The next step estimates how many of them can be active during the busiest school timetable slot.

## 2.X.2 Timetable Concentration Model

Pupils do not use DigitMile continuously throughout the week. They use it during IT-related school sessions. Let \(f\) denote the number of IT sessions per pupil per week, and let \(H\) denote the number of school period slots per week. The base values are:

```text
f = 2
H = 30
```

If IT classes were distributed perfectly uniformly across all weekly period slots, the probability that a given pupil is in an IT class during a randomly selected period would be:

```text
f / H = 2 / 30 = 0.0667
```

However, real timetables are not perfectly uniform. Some days can contain more IT classes than others, and within a day some periods can be more common than others. To avoid underestimating the busiest period, the model introduces two clustering factors:

```text
C_day    = clustering factor for the busiest day
C_period = clustering factor for the busiest period within that day
```

The base model uses:

```text
C_day = 1.5
C_period = 1.5
```

The probability that a shift-active pupil is in an IT class during the busiest period is:

```text
P_IT = (f / H) × C_day × C_period
```

Substituting the base values:

```text
P_IT = (2 / 30) × 1.5 × 1.5
     = 0.0667 × 2.25
     = 0.15
```

Thus, the model assumes that during the busiest school period approximately 15% of the shift-active adopted pupils are in an IT class. This is not an exact measurement of a national timetable; it is a conservative modeling assumption used to represent clustering in real school schedules.

The model also accounts for the fact that not all pupils are in school during the same shift. Let \(s_{morning}\) denote the fraction of pupils in the active shift at the modeled peak time:

```text
s_morning = 0.60
```

Finally, two additional multipliers are used:

```text
B = 1.3
S = 1.3
```

The factor \(B\) models additional overlap inside the active play window. Pupils do not start and finish at perfectly uniform times, and real classroom behavior can create short periods where more pupils are simultaneously mid-run. The factor \(S\) is a safety margin. It makes the benchmark target more conservative by assuming that the estimate may be too low.

The peak number of concurrently active pupils is therefore:

```text
CCU = N × s_morning × P_IT × B × S
```

For the medium-adoption scenario:

```text
CCU = 27,900 × 0.60 × 0.15 × 1.3 × 1.3
    = 27,900 × 0.09 × 1.69
    = 2,511 × 1.69
    ≈ 4,243
```

The result means that, under medium adoption, the system should be prepared for approximately 4,200 pupils playing at the same time during the busiest realistic school period.

## 2.X.3 Gameplay Completion Rate and Steady Ingest RPS

The next step is to convert concurrent active pupils into completed runs per second. Let \(T\) denote the average number of turns per run, and let \(w\) denote the average wall-clock duration of one turn in seconds:

```text
T = 20
w = 20 seconds
```

The average run duration \(R\) is:

```text
R = T × w
```

With the base values:

```text
R = 20 × 20
  = 400 seconds
```

This corresponds to approximately 6.7 minutes per run. If \(CCU\) pupils are actively playing and each run lasts \(R\) seconds on average, then the average rate at which runs finish is:

```text
RPS_steady = CCU / R
```

For medium adoption:

```text
RPS_steady = 4,243 / 400
           ≈ 10.6
           ≈ 11 requests/second
```

Since every completed run produces exactly one ingest HTTP request, this completion rate is also the steady ingest request rate. This is the source of the 11 RPS sustained ingest target used in the benchmark scenarios.

The formula can also be understood as a flow-rate relationship:

```text
throughput = concurrency / average duration
```

With 4,243 pupils in progress and an average run duration of 400 seconds, approximately one four-hundredth of those runs finish each second. Therefore, the backend receives about 11 completed-run payloads per second in the steady medium-adoption case.

## 2.X.4 Lesson-Bell Burst Model

The steady-state model describes normal overlapping gameplay, where run completions are distributed over time. A separate scenario is needed for short synchronized bursts near the end of a class. In a classroom setting, many pupils may finish or submit their last run close to the school bell. Even if the average steady rate is lower, the system must absorb this short peak without failing requests.

Let \(f_{burst}\) denote the fraction of pupils in the active IT classes who submit within the burst window, and let \(d_{burst}\) denote the duration of that window in seconds:

```text
f_burst = 0.70
d_burst = 60 seconds
```

The number of pupils submitting during the burst is:

```text
N_burst = N × s_morning × P_IT × f_burst
```

For medium adoption:

```text
N_burst = 27,900 × 0.60 × 0.15 × 0.70
        = 1,757.7
```

If these submissions arrive over a 60-second interval, the burst request rate is:

```text
RPS_burst = N_burst / d_burst
```

Therefore:

```text
RPS_burst = 1,757.7 / 60
          ≈ 29.3
          ≈ 29 requests/second
```

This is the source of the 29 RPS lesson-bell benchmark target for the medium-adoption scenario.

It is important to distinguish this value from the steady 11 RPS target. The 11 RPS scenario represents normal sustained operation. The 29 RPS scenario represents a short spike caused by synchronized classroom behavior. The system is expected to handle the spike without HTTP 5xx errors and then drain the Redis buffer shortly after the spike ends.

## 2.X.5 Low, Medium, and High Adoption Scenarios

The same formulas can be applied to different adoption levels. Keeping all other base assumptions unchanged gives the following scenario table:

| Scenario | Adoption \(A\) | Present adopted pupils \(N\) | Peak active pupils \(CCU\) | Steady ingest RPS | 60-second burst RPS |
| -------- | -------------- | ---------------------------- | -------------------------- | ----------------- | ------------------- |
| Low adoption | 0.25 | 13,950 | 2,122 | 5.3 | 14.6 |
| Medium adoption | 0.50 | 27,900 | 4,243 | 10.6 ≈ 11 | 29.3 ≈ 29 |
| High adoption | 0.75 | 41,850 | 6,365 | 15.9 ≈ 16 | 43.9 ≈ 44 |

The medium-adoption scenario is used as the main non-functional requirement baseline because it represents a realistic national deployment target for a first large-scale rollout. The high-adoption scenario is useful as an additional stress or growth scenario. The low-adoption scenario shows that the target load scales linearly with adoption.

The key benchmark targets derived from this table are:

```text
medium steady ingest: 11 RPS
medium lesson-bell burst: 29 RPS
high steady ingest: 16 RPS
high lesson-bell burst: 44 RPS
```

## 2.X.6 Overload Recovery Target

The overload recovery benchmark is derived from the medium steady-state target. Since the sustained target is approximately 11 RPS, a two-times overload is:

```text
RPS_overload = 2 × 11 = 22 requests/second
```

The overload scenario therefore tests a temporary period at 22 RPS followed by a return to the supported 11 RPS load. The purpose of this benchmark is not to claim that 22 RPS is the normal guaranteed operating level on the target infrastructure. Rather, it tests whether the system can recover after a deliberate overload once traffic returns to the expected supported level.

This distinction is important for interpreting the results. If the system experiences increased latency or drops during the overload phase, that does not necessarily violate the requirement. The requirement is that the system returns to acceptable latency, drains its Redis queue, and avoids manual intervention after the overload ends.

## 2.X.7 Payload Size and Write Amplification

The HTTP request rate alone does not describe the full backend workload. Each completed run contains multiple turns and therefore produces multiple database rows when the Flusher persists the payload.

Let \(K_{base}\) denote fixed metadata and map overhead per run, and \(K_{turn}\) denote the average payload size per turn:

```text
K_base = 1.5 KB
K_turn = 0.7 KB
```

The approximate payload size per run is:

```text
K_payload = K_base + K_turn × T
```

With \(T = 20\):

```text
K_payload = 1.5 + 0.7 × 20
          = 15.5 KB
```

At the medium steady rate:

```text
bandwidth = 15.5 KB × 10.6 / 1024
          ≈ 0.16 MB/s
```

At the medium burst rate:

```text
bandwidth = 15.5 KB × 29.3 / 1024
          ≈ 0.44 MB/s
```

These values show that network bandwidth is not the primary bottleneck. The more important costs are JSON parsing, Pydantic validation, Redis buffering, batch insertion into PostgreSQL, index maintenance, and later analytical reads.

The number of turn rows written by the Flusher is also relevant. Each run produces approximately \(T\) `TurnEvent` rows. The steady `TurnEvent` insertion rate can be estimated as:

```text
TurnEvents_per_second = RPS_steady × T
```

Since:

```text
RPS_steady = CCU / (T × w)
```

then:

```text
TurnEvents_per_second = (CCU / (T × w)) × T
                       = CCU / w
```

For the medium scenario:

```text
TurnEvents_per_second = 4,243 / 20
                       ≈ 212 turn rows/second
```

This explains why the Flusher uses batch inserts. Although the HTTP rate is only around 11 requests per second in the steady case, the database write path must persist hundreds of turn-level rows per second, plus any `SpecialTileTrigger` rows generated by special tile effects.

## 2.X.8 Mapping the Load Model to Benchmarks

The benchmark scenarios used in the evaluation chapter follow directly from the formulas above:

| Derived value | Benchmark interpretation |
| ------------- | ------------------------ |
| 11 RPS | sustained medium-adoption ingest target |
| 29 RPS | medium-adoption lesson-bell burst |
| 16 RPS | sustained high-adoption ingest target |
| 44 RPS | high-adoption lesson-bell burst |
| 22 RPS | 2x overload relative to the medium steady target |
| 20 turns/run | benchmark dataset average turn count |
| 15.5 KB/run | approximate payload size for Redis and network pressure |

This mapping is important because it connects the mathematical model to the empirical validation. The k6 tests are not simply stress tests chosen by intuition; they instantiate specific operating regimes:

1. sustained steady operation;
2. short synchronized burst;
3. mixed teacher-dashboard and ingest traffic;
4. overload followed by recovery;
5. compaction and historical-data maintenance.

## 2.X.9 Sensitivity of the Model

The model contains assumptions, and the thesis should acknowledge which assumptions have the strongest influence on the result.

The adoption factor \(A\) scales load linearly. If adoption doubles, the number of present adopted pupils, peak concurrent pupils, steady RPS, and burst RPS all approximately double.

The timetable concentration factors \(C_{day}\) and \(C_{period}\) are among the most important uncertainties. If IT classes are distributed uniformly, peak concurrency is lower. If many schools schedule IT classes on the same days and periods, peak concurrency is higher. This is why the model does not use only the uniform value \(f/H\), but multiplies it by clustering factors.

The run duration \(R\) affects steady RPS. Shorter runs increase RPS because pupils finish more frequently. Longer runs reduce RPS, but may increase payload size if the number of turns grows. The model makes this trade-off explicit through:

```text
R = T × w
RPS_steady = CCU / R
```

The burst duration \(d_{burst}\) has a strong effect on burst RPS. If the same number of submissions arrives in 30 seconds instead of 60 seconds, burst RPS doubles:

```text
RPS_burst = N_burst / d_burst
```

For medium adoption:

```text
60-second burst: 1,758 / 60 ≈ 29 RPS
30-second burst: 1,758 / 30 ≈ 59 RPS
```

Therefore, the lesson-bell benchmark must always be interpreted together with its assumed burst window.

## 2.X.10 Summary

The resulting benchmark targets are derived from the expected deployment model of DigitMile. Because the Unity client submits one request per completed run, the main steady-state ingest target is based on run completion rate rather than per-turn event rate. For the medium-adoption scenario, the model estimates approximately 4,243 concurrently active pupils during the busiest period. With an average run duration of 400 seconds, this produces approximately 11 ingest requests per second. A separate lesson-bell burst model estimates that synchronized submissions near the end of a class can produce approximately 29 requests per second for a short 60-second interval.

These values define the main non-functional requirements and benchmark scenarios. The sustained 11 RPS benchmark validates normal operation, the 29 RPS burst benchmark validates short peak absorption, and the 22 RPS overload benchmark validates recovery after traffic temporarily exceeds the expected steady-state target. The same model also explains why Redis buffering and batch persistence are appropriate architectural choices: HTTP requests arrive as completed-run payloads, while the database write path expands each payload into multiple turn-level rows that must be persisted efficiently.

## Optional Defense Notes

These notes are not intended for direct inclusion in the thesis, but they are useful for oral defense preparation.

### Why not use number of turns as HTTP RPS?

Because turns are included inside the completed-run payload. Turns affect payload size and database write amplification, but not HTTP request count.

### Why is CCU not equal to all adopted pupils?

Because only a fraction of pupils are in school, in the active shift, in an IT period, and actively playing during the busiest window.

### Why use clustering factors?

Because school timetables are not perfectly uniform. Clustering factors avoid underestimating the busiest period.

### Why have both steady and burst RPS?

They model different traffic regimes. Steady RPS is the normal completion flow. Burst RPS models synchronized submissions near the bell.

### Why is 22 RPS used for overload?

It is exactly 2x the medium steady target of 11 RPS. It tests recovery after overload, not normal sustained service capacity.

### What if the assumptions change?

The model is recalculable. Change the relevant parameter, recompute `CCU`, `R`, `RPS_steady`, and `RPS_burst`, and update the benchmark targets.

