# Capacity Math Correction — Run-Based Ingest Model

> ⚠️ **OUTDATED — DO NOT USE FOR NUMBERS.** This document was the initial derivation that motivated the corrected ingest model. Its body uses `T=27` and a 27-turn payload, both of which were superseded after gameplay testing showed the real turn distribution is narrower and lower (T≈20, max ~22–25 even at L6). It is preserved for historical context only.
>
> **Canonical reference:** `docs/research/ingest-capacity-model.md` — use that doc for all current numbers, the scenario table, sensitivity analysis, and k6 mapping.

**Status:** outdated (2026-05-11) — kept for historical context
**Supersedes (historically):** the ingest-RPS sections of `docs/research/north-macedonia-weekly-load-estimate.md`, the per-student request-rate assumption in `benchmarks/README.md` ("1.3 turns/min"), and the `ingest_rate_per_sec` values in `benchmarks/scenarios/national_medium.json` / `national_high.json`.
**Superseded by:** `docs/research/ingest-capacity-model.md` (T=20 corrected after gameplay testing).
**Not affected:** the population baseline, adoption fractions, attendance, timetable clustering, and safety factors in the existing research doc — those are still load-bearing inputs.

---

## 1. Why this exists

The earlier load model treated DigitMile as a "chatty" web app that produces 6–10 requests per active user per minute, and the benchmark scenarios further conflated turns-per-minute with ingest-RPS. Both are wrong for *this* stack. There is exactly one HTTP request per finished Run — never per turn, never per heartbeat. Correcting the per-student request rate changes the steady-state RPS target by roughly an order of magnitude and reshapes what the benchmark suite should measure.

This document re-derives the math from the actual ingest semantics so the benchmark scenarios, the README, and the eventual thesis chapter all agree.

## 2. Ingest call semantics (the load-bearing fact)

The Unity client posts exactly one HTTP request to `POST /panel/api/runs/ingest/` per completed Run. That request carries the full payload — Run metadata, every TurnEvent for that run, every chained SpecialTileTrigger, and the game map. There is no per-turn endpoint, no heartbeat, no leaderboard polling, no session-start/finish split. Outside class hours, traffic is negligible.

Two consequences fall straight out:

1. **Per-student request rate is `1 / mean_run_seconds`.** Anything that derives RPS from turn count or from a fixed think time per request is wrong by construction.
2. **Per-request CPU and bytes scale with `mean_turns_per_run`.** A longer run produces a bigger payload and more work for the synchronous-side validator, but does not produce more requests.

The combination matters: if students play longer per run, RPS falls *and* per-request cost rises. Total `turnevent` rows inserted per unit of clock time is approximately conserved, because total active-play minutes per student per week is fixed by the timetable. That conservation property is the load-bearing invariant for the flusher.

## 3. Turn-count distribution

Earlier scenarios used `avg_turns_per_run = 6`, anchored on dataset-prep convenience rather than observed gameplay. The game's actual mechanics — a 60-tile board, three-card hands, "back" cards that recur in late-level decks, a clown special tile that pulls players back four tiles, a skateboard tile capped at two-chain reach — guarantee that a *best-case* run on the easier levels still takes ~10–12 turns. Real play is longer.

Semester-weighted estimate, anchored on a three-trimester level rollout:

| Trimester | Levels played | Turn count range | Mean |
|---|---|---|---|
| T1 | L1–L2 | 15–30 | ~22 |
| T2 | L3–L4 | 20–35 | ~27 (interpolated) |
| T3 | L5–L6 | 25–40 | ~32 |
| **Semester-weighted average** | — | — | **~27** |

This is the input to every downstream formula in this document. The point estimate is good enough for capacity planning; once real telemetry is available, `mean_turns_per_run` should be computed directly from `TurnEvent` rows grouped by `Run.id`, and the table updated.

## 4. Wall-time per turn

Per-turn wall time matters not as a payload field (`cardDecisionTimeMs`, `numberDecisionTimeMs` are just numeric content) but because `mean_run_seconds = mean_turns_per_run × wall_time_per_turn`. The wall time determines how many runs fit in the 15-minute play window of an IT lesson, which sets the per-student λ.

Estimate, conservatively rounding the student-stated 20–30 s overshoot down to its lower bound:

```
wall_time_per_turn ≈ 20 s   (card decision + number decision + animation + UI)
```

That makes:

```
mean_run_seconds ≈ 27 × 20 s ≈ 540 s   (9 minutes)
```

Cross-check: a 15-minute play window fits roughly 1.6 runs at this length, consistent with the dataset's `runs_per_student_per_week = 3` against 1–2 IT lessons/week.

## 5. Per-student ingest rate

```
λ_student_ingest = 1 / mean_run_seconds
                 = 1 / 540 s
                 ≈ 0.00185 ingest/s   (during active gameplay)
```

For comparison:

- The earlier "1.3 turns/min" figure, if treated as ingest/min, gave `λ ≈ 0.022 ingest/s` — overstating per-student load by ~12×.
- Perplexity's heartbeat-driven `0.089 req/s` — overstating by ~48×.

## 6. Steady-state peak ingest RPS

Using the population and concurrency inputs already accepted in `north-macedonia-weekly-load-estimate.md`:

```
RPS_ingest_steady = CCU_peak × λ_student_ingest
```

| Adoption scenario | CCU peak | Steady ingest RPS |
|---|---|---|
| Medium (50% adoption, ~1,580 CCU) | 1,580 | **~3 ingest/s** |
| High (75% adoption, ~2,370 CCU) | 2,370 | **~4 ingest/s** |
| Pessimistic (every factor stacked, ~10,700 CCU) | 10,700 | **~20 ingest/s** |

This is the "background hum" of national-scale operation. None of these numbers are within an order of magnitude of saturating a 2 vCPU box, and they are far below the 35–52 RPS currently asserted in `national_medium.json` / `national_high.json`.

## 7. Lesson-bell burst (the load event that actually matters)

Steady-state RPS understates peak. The real load event is the end of the IT play window: 30 students per classroom finish their last run within a few minutes and submit roughly simultaneously. If many schools' IT periods coincide at the same wall-clock time slot, the bursts stack.

Burst model:

```
RPS_burst_peak = (students_per_classroom × classes_active_simultaneously) / burst_window_seconds
```

For the high-adoption scenario, taking `P(in_IT_period_now) = 0.30` from the existing study and a 5-minute drain window:

```
classes_active_simultaneously ≈ N_schools × classes_per_school × P
                              ≈ 1,500 × 0.30
                              ≈ 450 classes
finishers_during_window       ≈ 30 × 450 ≈ 13,500 runs
RPS_burst_peak                ≈ 13,500 / 300 s ≈ 45 ingest/s for ~5 min
```

A narrower 60-second tail of the drain window — students rushing to submit before the bell — sees a higher transient. This is the regime the `lesson_bell` scenario needs to model; steady-state arrival-rate executors do not capture it.

## 8. Payload size

The size of one ingest payload scales linearly with turns:

```
payload_KB ≈ 1.5 + 0.7 × mean_turns_per_run
```

At `mean_turns_per_run = 27` that puts a typical payload near **~20 KB**, versus the ~3 KB synthetic payload the current `buildUnityPayload` produces (2 turns). Implications:

| Effect | Impact |
|---|---|
| `json.loads(request.body)` cost | ~7× larger input, linear scan |
| `UnityIngestPayload.model_validate` | walks every turn; cost ~linear in `mean_turns_per_run` |
| `normalize_unity_run_ingestion_payload` | walks every turn again |
| Redis buffer item size | ~20 KB per buffered item |
| `_extract_card_metadata` in the flusher | runs per card; the dominant CPU cost in the flusher |
| TurnEvent rows per flush batch | 50 runs × 27 turns ≈ 1,350 rows per batch |

The flusher's per-batch insert volume is the parameter that makes "COPY vs. `bulk_create`" a measurable optimization. At 300 rows per batch (the old assumption), the difference is marginal; at 1,350+ rows per batch (corrected), it becomes worth its own thesis subsection.

## 9. Invariant: total TurnEvent insert rate is independent of run length

Total active-play minutes per student per week is fixed by the timetable. If runs become longer, students complete fewer of them, but each carries more turns. The product is approximately conserved:

```
turn_events_per_student_per_week ≈ active_minutes/week × 60 / wall_time_per_turn
                                 ≈ 30–45 × 60 / 20
                                 ≈ 90–135 TurnEvents/student/week
```

This is the rate the flusher must sustain on average. It is not affected by the corrections above; only the per-Run *batching* of those inserts changes. The implication is that the flusher's PG-write side does not get easier as run length grows — only the HTTP side does (fewer requests, bigger each).

## 10. Knock-on effects on the existing benchmark suite

| Artifact | Bias | Direction |
|---|---|---|
| `benchmarks/scenarios/national_high.json` `ingest_rate_per_sec: 52` | 6× too high under corrected steady-state | Lower to ~4–5; reserve 45+ RPS for `lesson_bell`. |
| `benchmarks/scenarios/national_medium.json` `ingest_rate_per_sec: 35` | 8× too high | Lower to ~3. |
| `benchmarks/README.md:84` "1.3 turns/min" | Conflates turns with ingest calls | Replace with `1 / mean_run_seconds`. |
| `benchmarks/k6/common.js:buildUnityPayload` (2 turns hard-coded, level 5 only) | 13× too few turns, no level variability | Parametrize via env: mean turns, std, level mix. |
| `benchmarks/k6/ingest.js:45` `fetchApiCsrf()` per iteration | Doubles HTTP load against own server | Move into `setup()` to match `mixed_weekly_cycle.js`. |
| `prepare_benchmark_dataset` default `avg_turns_per_run: 6` | 4–5× too thin; analytics baselines optimistic | Re-seed at ~27. |
| Lack of bell scenario | Real load event is invisible | Add `lesson_bell` scenario with 0→peak in ~10 s, hold 60 s, drain 30 s. |

## 11. What this means for the thesis

Two distinct load events, two distinct bottleneck profiles, are now the framing:

1. **Steady-state ingest** — 3–20 RPS, but each request is ~20 KB and triggers ~27-turn validation. Per-request CPU dominates. This is the regime where R1 (drop the PG round-trips on the hot path) and R2 (sync WSGI → async ASGI) deliver their measured wins.
2. **Lesson-bell burst** — ~45 RPS for ~1–5 minutes. Burst arrival queues up at Gunicorn before reaching Redis. The Redis write buffer absorbs the burst; PG never sees it directly. This is the regime that makes the buffered architecture (R0 in spirit, already shipped) defensible vs. a synchronous-insert baseline.

The corrected math is what makes the buffered-vs-synchronous comparison meaningful: at 4 RPS sustained, the buffer is irrelevant; at a 45-RPS spike, it's the difference between 202s and 5xx storms.

## 12. Open inputs to revisit once real telemetry exists

1. `mean_turns_per_run` per level — compute from `TurnEvent` once data is available; the table in §3 is a planning estimate.
2. `wall_time_per_turn` — derive from `Run.run_started_unix_ms` to `run_ended_unix_ms` divided by turn count; the 20 s figure is a conservative student estimate.
3. `P(in_IT_period_now)` — currently 0.30 (inherited). The single largest sensitivity; measure once any school timetables are loaded into the system.
4. Burst window length — modelled as 5 min in §7. Tighter windows produce higher peak; a 60-second tail of the drain is the worst credible micro-burst.

## 13. Implementation order

1. ✅ This document.
2. Re-seed: update `prepare_benchmark_dataset` defaults and scenario JSONs to `avg_turns_per_run ≈ 27` with trimester profile if practical.
3. k6: parametrize `buildUnityPayload` (mean turns / std / level mix), fix `ingest.js` CSRF, correct `national_*.json` rates, add `lesson_bell` scenario.
4. Toggle architecture: scaffolding for enabling/disabling shipped optimizations under benchmark.
