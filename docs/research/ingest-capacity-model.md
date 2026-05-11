# DigitMile Run-Ingest Capacity Model

**Self-service formula reference for CCU and RPS calculation.**
Supersedes `run_capacity_plan (1).md`. Companion to `docs/decisions/capacity-math-correction.md` (the derivation), `docs/decisions/hardware-sizing.md` (benchmark results), and `docs/research/north-macedonia-weekly-load-estimate.md` (population baseline).

---

## 1. Request model (what the game actually sends)

| Event | HTTP call | Frequency | Notes |
|---|---|---|---|
| CSRF bootstrap | `GET /panel/api/fetchCSRFToken/` | Once per browser session | Cached across runs; negligible |
| Student credential check | `POST /panel/api/checkStudentCredentials/` | Once per game launch | Negligible |
| Classroom key resolution | `POST /panel/api/checkClassroomKey/` | Once per game launch | Negligible |
| **Run ingest** | `POST /panel/api/runs/ingest/` | **1 per completed run** | The only load-bearing request |

There are **no heartbeats, no per-turn submissions, no mid-game pings**. The Unity client accumulates all turn data locally and sends the entire run as one atomic JSON payload when the game finishes. The backend pushes validated payloads into a Redis buffer; a separate flusher worker drains them into PostgreSQL in batched transactions.

Per-IT-session HTTP flow for one student:

```
fetchCSRFToken ──▶ checkStudentCredentials ──▶ checkClassroomKey
                                                      │
   ┌──────────────────────────────────────────────────┘
   ▼
   [play run 1] ──▶ POST /runs/ingest/
   [play run 2] ──▶ POST /runs/ingest/
   [play run 3] ──▶ POST /runs/ingest/
```

Consequence: RPS is driven by **how many runs finish per unit time**, not by turns or by think-time pacing within a run. Every formula below derives from this fact.

---

## 2. Input parameters

Change any value in the "Base" column to recalculate all downstream numbers. The "Range to try" column gives defensible bounds for sensitivity analysis.

### 2.1 Population and adoption

| Parameter | Symbol | Base value | Range to try | Source |
|---|---|---|---|---|
| Grade 4–6 students nationally | `N_pop` | 60,000 | Fixed | State Statistical Office (2023/24) |
| Adoption fraction | `A` | 0.50 | 0.25 / 0.50 / 0.75 | Scenario choice |
| Attendance rate | `a` | 0.93 | 0.88–0.95 | Typical primary school attendance |
| Adopted + present students | `N` | `N_pop × A × a` | — | Derived |

### 2.2 Timetable structure

| Parameter | Symbol | Base value | Range to try | Source |
|---|---|---|---|---|
| IT sessions per student per week | `f` | 2 | 1–2 | Curriculum minimum: 2×/week |
| Class duration (minutes) | — | 45 | Fixed | Standard Macedonian period |
| Play window at end (minutes) | — | 15 | 12–18 | Teacher discretion |
| School days per week | — | 5 | Fixed | |
| Periods per school day | `n_periods` | 6 | 5–7 | Typical 5–6 hours/day |
| Total period slots per week | `H` | 30 | 25–35 | 5 × 6 |
| Students per classroom | `n_class` | 25 | 20–30 | Typical Macedonian class |
| Morning-shift fraction | `s_morning` | 0.60 | 0.50–0.65 | 60% morning, 40% afternoon |
| Timetable clustering — day | `C_day` | 1.5 | 1.0–2.0 | How much IT clusters on busiest day vs. uniform |
| Timetable clustering — period | `C_period` | 1.5 | 1.0–1.8 | How much IT clusters in busiest period of that day |

### 2.3 Gameplay timing

| Parameter | Symbol | Base value | Range to try | Source |
|---|---|---|---|---|
| Mean turns per run (semester-weighted) | `T` | 20 | 15–25 | Even across levels: L1-2→~18, L3-4→~20, L5-6→~22. Max observed ~22-25. |
| Wall-time per turn (seconds) | `w` | 20 | 15–30 | Player decision (~27s in complex levels) + bot animation; student testing suggests ~20s effective |
| Mean run wall-time (seconds) | `R` | `T × w` | — | Derived: 20 × 20 = 400 s (~6.7 min) |
| Runs per student per 15-min session | `r_session` | 2.5 | 2–3 | Student testing: ~2–3 runs in 15 min (consistent with 6.7 min runs) |
| Runs per student per week | `r_week` | `f × r_session` | — | Derived: 2 × 2.5 = 5 |

### 2.4 Burst behaviour

| Parameter | Symbol | Base value | Range to try | Source |
|---|---|---|---|---|
| Burst drain window (seconds) | `d_burst` | 60 | 30–300 | Narrow = higher peak. 60s = students rushing last run before bell; 300s = relaxed finish |
| Fraction of in-class students finishing within burst | `f_burst` | 0.7 | 0.5–1.0 | How many complete their last run within the drain window |

### 2.5 Safety and fudge factors

| Parameter | Symbol | Base value | Range to try | Source |
|---|---|---|---|---|
| Concurrency clustering factor | `B` | 1.3 | 1.0–1.7 | Uneven distribution within the play window |
| Safety margin | `S` | 1.3 | 1.0–1.5 | Thesis defensibility margin |

### 2.6 Payload sizing

| Parameter | Symbol | Base value | Range to try | Source |
|---|---|---|---|---|
| Payload overhead (KB) | — | 1.5 | Fixed | Run metadata + game map |
| Payload per turn (KB) | — | 0.7 | 0.5–1.0 | Card data, positions, triggers |

---

## 3. Step 1 — Peak concurrent students (CCU)

### Formula

```
P_IT = (f / H) × C_day × C_period

N_in_IT_class = N × s_morning × P_IT

CCU = N_in_IT_class × B × S
```

### What each factor means

- **`(f / H)`** — If IT sessions were perfectly uniform across all 30 period slots, a student has a `2/30 ≈ 6.7%` chance of being in IT at any given slot. This is the baseline.

- **`C_day`** — IT classes are not spread evenly across all 5 days. If twice as many IT classes happen on Tuesday vs. a uniform distribution, `C_day = 2.0`.

- **`C_period`** — Within the busiest day, IT classes favour certain periods (e.g., mid-morning). If the peak period has 50% more IT classes than the day's average, `C_period = 1.5`.

- **`P_IT`** — The fraction of **shift-active** students whose 45-minute IT class overlaps the single busiest period slot. With the base values: `(2/30) × 1.5 × 1.5 = 0.15` (15%).

- **`s_morning`** — Only one shift is active at the peak. If morning = 60%, afternoon students are not CCU at the morning peak. This roughly halves peak concurrency vs. a single-shift assumption.

- **`B`** — Within the peak play window, not all students are mid-run at exactly the same instant. Some are between runs, some just started, some just finished. `B ≈ 1.0` if the play window is uniformly saturated; `B > 1.0` if runs tend to overlap more than expected.

- **`S`** — Thesis safety margin. Multiply by 1.3 to say "our estimate could be 30% low."

### Worked example (base values)

```
P_IT       = (2 / 30) × 1.5 × 1.5  = 0.15
N          = 60,000 × 0.50 × 0.93  = 27,900
N_in_IT    = 27,900 × 0.60 × 0.15  = 2,511
CCU        = 2,511 × 1.3 × 1.3     ≈ 4,243
```

**Interpretation:** At 50% adoption, roughly 4,200 students are mid-run simultaneously during the single busiest 10–15 minute slice of the school week.

---

## 4. Step 2 — Steady-state ingest RPS

### Formula

```
R = T × w

RPS_steady = CCU / R
```

### Why this works

With CCU students mid-run and each run lasting `R` seconds, runs complete at a rate of `CCU / R` per second. Each completion produces exactly 1 POST to `/runs/ingest/`.

### Worked example

```
R          = 20 × 20  = 400 s
RPS_steady = 4,243 / 400 ≈ 10.6 ingest/s
```

### Per-student request rate (for cross-check)

```
λ_student = 1 / R = 1 / 400 ≈ 0.0025 ingest/s
```

Compare to the old (wrong) heartbeat model: `0.089 req/s` — **36× overstatement**.

---

## 5. Step 3 — Lesson-bell burst RPS

This is the transient spike when multiple classrooms finish their play window simultaneously. It is a separate load regime from steady-state.

### Formula

```
N_burst = N × s_morning × P_IT × f_burst

RPS_burst = N_burst / d_burst
```

### Worked example

```
N_burst    = 27,900 × 0.60 × 0.15 × 0.7  = 1,758 students
RPS_burst  = 1,758 / 60  ≈ 29.3 ingest/s
```

**Interpretation:** For roughly 60 seconds, the ingest endpoint sees ~29 requests/second as students submit their final run before the bell. This is the peak the system actually needs to absorb without queuing failures.

With a 300-second drain window (relaxed finish): `1,758 / 300 ≈ 5.9 ingest/s` — basically steady-state.

The burst is only relevant if **bell schedules synchronise** across many schools. If drain windows spread over 5+ minutes, the burst disappears and steady-state RPS is the binding number.

---

## 6. Step 4 — Payload volume and flusher throughput

### Payload size per run

```
payload_KB = 1.5 + 0.7 × T
           = 1.5 + 0.7 × 20 ≈ 15.5 KB
```

### Total ingress bandwidth (steady-state)

```
bandwidth_MBps = payload_KB × RPS_steady / 1024
               = 15.5 × 10.6 / 1024 ≈ 0.16 MB/s
```

Negligible at any adoption tier.

### Redis buffer pressure

```
buffer_items_per_second = RPS_steady
buffer_size_per_second_KB = payload_KB × RPS_steady
```

At base values: ~11 items/s, ~170 KB/s. The flusher drains batches of 50 runs (~775 KB) every 100 ms by default. A burst of 29 RPS for 60 seconds puts ~1,740 items in the buffer (~27 MB). Redis's 256 MB allocation absorbs this comfortably.

### Flusher: TurnEvent insert rate

```
turn_events_per_second = CCU / w
                       = 4,243 / 20 ≈ 212 rows/s
```

Within one flusher batch (50 runs × 20 turns = 1,000 rows): batch completes in ~4.7 seconds at 212 rows/s. The flusher at 100ms polling comfortably stays ahead.

---

## 7. Scenario table

Base parameters held constant (from §2) unless noted.

| Metric | Low (25%) | Medium (50%) | High (75%) | Pessimistic |
|---|---|---|---|---|
| **Adoption `A`** | 0.25 | 0.50 | 0.75 | 0.75 |
| **`P_IT`** | 0.15 | 0.15 | 0.15 | **0.30** |
| **`f_burst`** | 0.7 | 0.7 | 0.7 | **0.9** |
| **`B`** | 1.3 | 1.3 | 1.3 | **1.7** |
| **`S`** | 1.3 | 1.3 | 1.3 | **1.5** |
| **`w` (s)** | 20 | 20 | 20 | **15** |
| **`T`** | 20 | 20 | 20 | **25** |
| Students present (`N`) | 13,950 | 27,900 | 41,850 | 41,850 |
| Students in IT at peak | 1,256 | 2,511 | 3,767 | 7,533 |
| **CCU peak** | **2,121** | **4,243** | **6,365** | **19,209** |
| Mean run wall-time (`R`, s) | 400 | 400 | 400 | 375 |
| **Steady RPS** | **5.3** | **10.6** | **15.9** | **51.2** |
| RPS per student (`λ`) | 0.0025 | 0.0025 | 0.0025 | 0.0027 |
| Burst students | 879 | 1,758 | 2,636 | 6,780 |
| **Burst RPS (60s window)** | **14.6** | **29.3** | **43.9** | **113.0** |
| Payload KB/run | 15.5 | 15.5 | 15.5 | 19.0 |
| Bandwidth (MB/s steady) | 0.08 | 0.16 | 0.24 | 0.95 |
| TurnEvents/s to flusher | 106 | 212 | 318 | 1,281 |
| Runs/week | 69,750 | 139,500 | 209,250 | 209,250 |

> **Pessimistic column:** Every adjustable factor set to worst-case. `T` uses the upper bound of observed turn counts (25). `w` uses the minimum plausible wall-time (15s). Represents the upper bound for thesis defence, not an expected operating point. Reaching 113 burst RPS would require both extreme timetable clustering and near-perfect bell synchronisation across hundreds of schools — unlikely in practice.

---

## 8. Sensitivity playground

Change one parameter while holding others at base (medium adoption). Observe how CCU and RPS respond.

### Adoption `A`

| A | CCU | Steady RPS | Burst RPS |
|---|---|---|---|
| 0.25 | 2,121 | 3.9 | 14.6 |
| 0.50 | 4,243 | 7.9 | 29.3 |
| 0.75 | 6,365 | 11.8 | 43.9 |

**Effect:** Linear. Doubling adoption doubles all load metrics.

### Timetable clustering `P_IT`

Vary `C_day` and `C_period` to change `P_IT`.

| C_day | C_period | P_IT | CCU | Steady RPS | Burst RPS |
|---|---|---|---|---|---|
| 1.0 | 1.0 | 0.067 | 1,886 | 3.5 | 13.0 |
| 1.5 | 1.5 | 0.150 | 4,243 | 7.9 | 29.3 |
| 2.0 | 1.5 | 0.200 | 5,658 | 10.5 | 39.1 |
| 2.0 | 1.8 | 0.240 | 6,789 | 12.6 | 46.9 |

**Effect:** This is the single largest lever. At uni clustering (`C_day=1.0, C_period=1.0`), CCU drops to ~1,900. At strong clustering (`C_day=2.0, C_period=1.8`), CCU nearly doubles the base estimate. **Measure this from real timetables as early as possible.**

### Wall-time per turn `w`

| w | R (s) | Steady RPS | Runs/session |
|---|---|---|---|
| 15 | 405 | 10.5 | 2.2 |
| 20 | 540 | 7.9 | 1.7 |
| 25 | 675 | 6.3 | 1.3 |
| 30 | 810 | 5.2 | 1.1 |

**Effect:** Faster runs = higher RPS (more runs finish per unit time) but same total ingest volume per week (same total play time). `RPS × R = CCU` is constant for fixed CCU, so `RPS ∝ 1/w`.

Note at `w=30`: roughly 1.5 runs fit in 15 minutes, at the low end of observed 2–3 runs/session. This is consistent if `w` rarely exceeds 25s in practice.

### Mean turns per run `T`

| T | R (s) | Steady RPS | Payload KB |
|---|---|---|---|
| 15 | 300 | 14.1 | 12.0 |
| 18 | 360 | 11.8 | 14.1 |
| 20 | 400 | 10.6 | 15.5 |
| 22 | 440 | 9.6 | 16.9 |
| 25 | 500 | 8.5 | 19.0 |

**Effect:** More turns = longer runs = lower RPS but bigger payloads. Total `TurnEvent` insert rate is approximately conserved: `CCU / w` depends only on `w`, not `T`. Observed turn counts are surprisingly even across levels — the distribution is narrower than originally estimated.

### Burst drain window `d_burst`

| d_burst (s) | Burst RPS | Notes |
|---|---|---|
| 30 | 58.6 | All last-runs submitted in 30 s — tight bell |
| 60 | 29.3 | Base assumption |
| 120 | 14.6 | Relaxed finish |
| 300 | 5.9 | Essentially steady-state |

**Effect:** Only matters if bell synchronisation exists. If schools' IT periods end at staggered times within a 5-minute band, there is no burst — just steady-state with a gentle hump.

### Safety margin `S` and clustering `B`

These are pure multipliers on CCU (and thus RPS). `CCU ∝ B × S`. At base (`B=1.3, S=1.3`): multiplier = 1.69. Stripping both (`B=1.0, S=1.0`): CCU = 2,511. Maxing both (`B=1.7, S=1.5`): CCU = 6,403.

---

## 9. Direct mapping to k6 benchmark parameters

| k6/scenario parameter | Derives from | For base medium scenario |
|---|---|---|
| `ingest_rate_per_sec` (steady) | `RPS_steady` (§4) | **11** (not 35) |
| `ingest_rate_per_sec` (bell spike) | `RPS_burst` (§5) | **30** (60s window) |
| `avg_turns_per_run` (dataset prep) | `T` (§2.3) | **20** (not 6) |
| `buildUnityPayload()` turn count | `T` with level bracket | L1-2: ~18, L3-4: ~20, L5-6: ~22 |
| `duration` (steady scenario) | `d_burst` or longer soak | 15 min soak |
| `duration` (bell scenario) | `d_burst` + ramp | 10s ramp → hold 60s → 30s drain |
| VU sizing (ingest, arrival-rate) | `RPS_steady × p95_latency` | 11 × 0.2 = ~2 steady VUs; pre-allocate 20 |
| VU sizing (bell, ramping) | `RPS_burst × p95_latency` | 30 × 0.5 = ~15 peak VUs; pre-allocate 50 |
| CSRF fetch frequency | Once in `setup()`, not per iteration | Move from `default()` to `setup()` |

### New scenario: `lesson_bell.json`

This scenario does not exist yet. It should model:

```
executor: 'ramping-arrival-rate'
stages:
  - { duration: '10s', target: 0 }      // baseline
  - { duration: '10s', target: 30 }     // bell rings, surge
  - { duration: '60s', target: 30 }     // hold peak
  - { duration: '30s', target: 0 }      // drain
preAllocatedVUs: 50
maxVUs: 100
```

Target rate = `RPS_burst` from the scenarios table. Run this alongside steady-state scenarios to capture both load regimes.

### Scenario JSON correction table

| Scenario file | Current `ingest_rate_per_sec` | Corrected steady | Corrected burst |
|---|---|---|---|
| `national_medium.json` | 35 | ~11 | 30 |
| `national_high.json` | 52 | ~16 | 44 |
| `ingest_isolation.json` | 60 (ramp ceiling) | Keep as stress ceiling | Add bell scenario |

The corrected steady-state rates are **below** the measured ~17 req/s hardware ceiling (from `hardware-sizing.md`), meaning a 2 vCPU / 4 GB box should pass steady-state medium adoption at corrected rates and approach the ceiling at high adoption. The bell burst at high adoption (44 RPS) sits in the 40–60 req/s range that `hardware-sizing.md` recommends 4–8 vCPU for, but the Redis write buffer absorbs the spike — the bottleneck is Gunicorn accept queue depth, not PG write throughput.

---

## 10. Open unknowns (to measure from live telemetry)

| Unknown | Why it matters | How to measure |
|---|---|---|
| `mean_turns_per_run` per level | Drives `R` and `RPS_steady` | `SELECT level, AVG(turn_count) FROM (SELECT run_id, level, COUNT(*) as turn_count FROM digitmileapi_turnevent GROUP BY run_id, level) GROUP BY level` |
| `wall_time_per_turn` (real) | Drives `R` and `RPS_steady` | `(run_ended_unix_ms - run_started_unix_ms) / turn_count` from `Run` + `TurnEvent` rows |
| `P_IT` (timetable clustering) | Single largest CCU lever | Load school timetables → compute max overlap across all 45-min slots |
| Morning/afternoon shift ratio | CCU ~halved or not | Distribution of registered schools by shift |
| Run duration distribution (variance) | Burst vs. steady model validity | Histogram of `run_ended_unix_ms - run_started_unix_ms` |
| Animation frequency (special tiles hit) | Upper-bound wall-time per turn | Count `SpecialTileTrigger` rows per turn; long animations only trigger on clown/skateboard |

---

## 11. How to recalculate

1. Open §2. Change any parameter in the "Base value" column.
2. Follow the formulas in §3–§6, substituting your new value.
3. Each formula is self-contained — you can recompute any section independently.
4. Cross-check: `RPS_steady × R = CCU` must hold. If changing `T` or `w`, update `R` first.
5. The scenario table (§7) is the target output — fill in your row with your numbers and compare columns.

**Quick recalculation cheat:**

```
N      = 60,000 × A × a
P_IT   = (2 / 30) × C_day × C_period
CCU    = N × 0.60 × P_IT × B × S
R      = T × w
RPS    = CCU / R
BURST  = N × 0.60 × P_IT × f_burst / d_burst
PKT    = 1.5 + 0.7 × T         # payload KB per run
```
