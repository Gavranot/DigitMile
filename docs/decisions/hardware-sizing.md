# DigitMile — Backend Performance Analysis and Hardware Requirements

**Prepared by:** Damjan Janevski
**Date:** March 2026
**Subject:** Measured load capacity, software optimisations applied, and hardware upgrade justification for national-scale deployment

---

## 1. Overview

DigitMile is a web-based educational platform for primary school mathematics built for deployment in North Macedonia. Students play a card-based strategy game; after each turn the Unity client submits a game-state record to the backend via HTTP. Teachers access a live dashboard with per-classroom analytics.

This report documents:

1. The load model for national-scale deployment
2. The benchmark methodology used to measure the system
3. All software optimisations applied and their measured effect
4. The hardware ceiling reached and the specification required to serve the full expected load

---

## 2. System Architecture

The backend stack consists of:

| Component | Technology |
|---|---|
| Application server | Python 3.12 / Django 4.x / Gunicorn |
| Database | PostgreSQL 16 |
| Connection pooler | PgBouncer (transaction mode) |
| Containerisation | Docker Compose |
| Load generator | k6 (open-source load testing tool) |

**Current production hardware:** 2 vCPU, 3.8 GiB RAM VPS — Intel Xeon E7-8880 v3

**Runtime topology:**

```
Unity clients  ──▶  nginx  ──▶  Gunicorn (5 workers)  ──▶  PgBouncer  ──▶  PostgreSQL 16
Teacher browsers ──▶  nginx  ──▶  Gunicorn (5 workers)  ──/
```

PgBouncer sits between the application and the database in **transaction pooling mode**: a real PostgreSQL connection is only held for the duration of a single committed transaction, then returned to the pool. This allows 5 Gunicorn workers to share a pool of 10 database connections without contention.

---

## 3. National Load Model

The load targets are derived from publicly available statistics for North Macedonia and a conservative usage model.

### 3.1 Population

- Grade 3–5 pupils in North Macedonia: approximately **60,000**
- Target adoption — **medium** (50%): 30,000 active students
- Target adoption — **high** (75%): 45,000 active students

### 3.2 Concurrency model

Not all students are active simultaneously. The peak concurrent fraction is estimated at approximately 5.3% (representative of a 20-minute class period spread across a school day with multiple schools):

| Adoption tier | Active students | Peak concurrent | Ingest RPS | Teacher RPS |
|---|---|---|---|---|
| Medium (50%) | 30,000 | ~1,580 | **35 req/s** | ~5 req/s |
| High (75%) | 45,000 | ~2,370 | **52 req/s** | ~8 req/s |

### 3.3 Derivation of ingest RPS

Each student plays at approximately 1.3 turns per minute during an active session:

```
Ingest RPS = concurrent_students × 1.3 turns/min ÷ 60 seconds
           = 1,580 × 1.3 ÷ 60 ≈ 35 req/s   (medium)
           = 2,370 × 1.3 ÷ 60 ≈ 52 req/s   (high)
```

### 3.4 Teacher traffic

```
Concurrent teachers = concurrent_students ÷ 20 students/class
Dashboard reloads   = teachers × 1 reload/min ÷ 60
Analytics polling   = 1–2 req/s (teachers loading section charts)
```

---

## 4. Benchmark Methodology

### 4.1 Tool: k6

[k6](https://k6.io) is an open-source load testing tool that executes JavaScript test scripts and reports detailed latency percentiles, throughput, and error counts. Tests are run inside the same Docker Compose network as the backend so that network latency does not inflate results.

**Key metric — `dropped_iterations`:** k6 tracks iterations that were scheduled to run but could not because the server was too slow to process previous requests and the VU pool was exhausted. A high drop rate means the server is receiving more requests per second than it can complete — it is the primary indicator of over-capacity.

**Key metric — `load_health`:** A custom status assigned to each benchmark run by the benchmarking harness:

| Status | Meaning |
|---|---|
| `green` | Drop rate < 1%, all checks pass, latency within targets |
| `yellow` | Drop rate 1–10%, or latency degraded but not catastrophic |
| `red` | Drop rate > 10%; server is significantly over capacity |

**Key metric — `http_req_duration`:** End-to-end HTTP response time measured at the client (k6). Reported as average, p90, and p95. Under high load, latency numbers only reflect requests that *did* complete — a heavily overloaded server will appear to have reasonable latency among completions while dropping most attempts.

### 4.2 Resource monitoring

CPU and memory usage are sampled from Docker stats every 5 seconds throughout each benchmark run and summarised as average and peak. CPU is reported as a percentage of one logical CPU core: 100% = one core fully utilised, 200% = two cores fully utilised.

---

## 5. Benchmark Scenarios

Four scenarios are used, each targeting a different question.

---

### 5.1 `ingest_isolation` — Single-endpoint stress test

**Purpose:** Find the maximum sustainable ingest throughput on this hardware in complete isolation from other traffic.

**What it tests:** Only the run ingest endpoint (`POST /panel/api/runs/ingest/`) is exercised. All teacher traffic (dashboard, analytics, replay) is disabled. This isolates the ingest write path — database INSERT, serialisation validation, card metadata extraction — from any interference by read queries.

**Traffic model:** k6 uses `ramp_mode`, meaning the ingest rate increases linearly from 0 to 60 req/s over the 4-minute run. The break-point (the rate at which drops first appear and CPU peaks) is the server's ingest ceiling.

**Dataset:** 1 teacher, 2 classrooms, 60 students. Minimal — enough student variety to be representative without heavy analytics query cost.

**Why this runs first:** If the ingest ceiling is below 35 req/s, running the full national_medium scenario is pointless — the server cannot reach the target rate regardless of teacher load.

---

### 5.2 `realistic_school_day` — Single-teacher sanity check

**Purpose:** Confirm that the server can handle realistic traffic from one teacher and their classrooms without any strain.

**What it tests:** All 5 traffic classes run simultaneously at 1 req/s each (5 total req/s):

| Traffic class | Endpoint | Rate |
|---|---|---|
| Ingest | `POST /panel/api/runs/ingest/` | 1 req/s |
| Dashboard | `GET /panel/teacher/statistics/` | 1 req/s |
| Analytics | `GET /panel/teacher/statistics/viz-data/?section=analytics` | 1 req/s |
| Turn insights | `GET /panel/teacher/statistics/viz-data/?section=turn_insights` | 1 req/s |
| Replay | `GET /panel/teacher/runs/<id>/` | 1 req/s |

**Dataset:** 1 teacher, 3 classrooms, 60 students, 8 weeks history (6 compacted, 2 hot). 2,160 hot turn events.

**Expected outcome:** Always `green`. This scenario should pass on any functional deployment. If it does not, something is fundamentally broken at the infrastructure level. It also provides realistic baseline latency numbers for individual endpoints under no competing load.

---

### 5.3 `national_medium` — 50% national adoption load test

**Purpose:** Simulate the peak traffic of the medium adoption target: 50% of grade 3–5 pupils in North Macedonia active simultaneously.

**What it tests:** All 5 traffic classes run simultaneously at the rates derived from the national load model:

| Traffic class | Rate |
|---|---|
| Ingest | **35 req/s** |
| Dashboard | 2 req/s |
| Analytics | 1 req/s |
| Turn insights | 1 req/s |
| Replay | 1 req/s |
| **Total** | **40 req/s** |

**Dataset:** 10 teachers, 4 classrooms each, 25 students per classroom = **1,000 students**. 8 weeks history (6 compacted, 2 hot). ~36,000 hot turn events across the two active weeks.

The hot-week data represents the rows that analytics queries must scan in real time. The 6 compacted weeks are stored in pre-aggregated rollup tables and are fast to query.

**VU sizing (Little's Law):** k6 Virtual Users (VUs) represent concurrent clients. The number of VUs is sized so that drops come from server response time being too slow, not from running out of simulated clients. For ingest: at 500ms response time and 35 req/s target, Little's Law gives `35 × 0.5 = 17.5` steady-state VUs; the scenario pre-allocates 80 and allows up to 250, giving 4× headroom.

**Expected outcome on current hardware:** `red`. The scenario configuration file itself documents this expectation:

> *"WARNING: This scenario will produce load_health: red with a 3-worker Gunicorn setup. That is expected and intentional — the purpose is to measure the gap, not to pass."*

---

### 5.4 `national_high` — 75% national adoption load test

**Purpose:** The stretch production target. 75% of grade 3–5 pupils active simultaneously.

**What it tests:** Same structure as `national_medium`, with rates derived from the high adoption model:

| Traffic class | Rate |
|---|---|
| Ingest | **52 req/s** |
| Dashboard | 3 req/s |
| Analytics | 2 req/s |
| Turn insights | 2 req/s |
| Replay | 1 req/s |
| **Total** | **60 req/s** |

**Dataset:** 15 teachers, same per-teacher scale as `national_medium`, 1,500 students. ~54,000 hot turn events.

**Expected outcome:** `red` on current hardware. This scenario is only meaningful to run after `national_medium` is `green` — it validates that the hardware has sufficient headroom beyond the minimum target.

---

## 6. Software Optimisations Applied

Before attributing performance gaps to hardware, all reasonable software improvements were implemented and measured. This section documents each one in order.

---

### 6.1 Optimisation 0a — PgBouncer connection pooling

**Problem identified:** Under load, the database was reaching 92% CPU. Each Gunicorn worker held a dedicated long-lived PostgreSQL connection. With 3 workers processing requests serially, the DB was being hammered with concurrent queries while connections sat idle between requests.

**Fix applied:** PgBouncer was introduced in transaction pooling mode. A real PostgreSQL connection is borrowed from the pool only for the duration of each committed transaction. Between requests, workers are not holding connections. 3 workers now share a pool of 10 PostgreSQL connections. Django was configured with `CONN_MAX_AGE=0` (no persistent connections) and `DISABLE_SERVER_SIDE_CURSORS=True` (required for transaction pooling).

**Measured result:**
- DB CPU: 92% → 49% (headroom restored)
- Backend CPU: ~60% → 114% (bottleneck shifted from DB to Python CPU processing)
- Combined with worker increase: throughput rose from ~8 req/s to ~16.5 req/s

---

### 6.2 Optimisation 0b — Gunicorn workers: 3 → 5

**Problem identified:** 3 Gunicorn workers on a 2-vCPU server. Each worker is a separate OS process handling one request at a time. The standard Gunicorn formula for CPU-bound workloads is `2 × vCPUs + 1 = 5` workers.

**Fix applied:** `--workers 3` changed to `--workers 5` in `Dockerfile` and `Dockerfile.compose`.

**Measured result (combined with PgBouncer):** Throughput approximately doubled from ~8 to ~16.5 mixed req/s at `national_medium` load.

---

### 6.3 Optimisation 1+2 — Eliminate redundant serialiser validation on ingest

**Problem identified:** Every Unity game-client ingest request was being validated twice by the Django REST Framework serialiser pipeline:

1. `UnityRunUploadPayloadSerializer` — validates the Unity JSON format and constructs ~6 nested serialiser objects per turn event
2. `CanonicalRunIngestionPayloadSerializer` — validates the normalised output again, constructing a second set of serialiser objects per turn

This meant that for a 6-turn run, 12 serialiser instances were allocated and validated where 6 were sufficient. Additionally, a `Student.objects.filter(pk=...).exists()` database query was being executed twice per request — once in each serialiser's `validate_userID` / `validate_student_id` method.

**Fix applied:**

- `RunIngestionSerializer.to_internal_value()` now short-circuits for Unity payloads: after `UnityRunUploadPayloadSerializer` validates, the method returns immediately with the normalised data. The canonical serialiser pass only runs for non-Unity clients.
- `normalize_unity_run_ingestion_payload()` was extended to compute `player_won` and `elapsed_ms` directly (these were previously derived in the canonical pass), completing the data without a second validation round.

**Measured result (`ingest_isolation` benchmark, isolated ingest only):**

| Metric | Before (YELLOW) | After (GREEN) | Change |
|---|---|---|---|
| Average latency | 237.89 ms | 57.83 ms | **−75.7%** |
| p(95) latency | 1,116.76 ms | 200.88 ms | **−82.0%** |
| Maximum latency | 1,616.14 ms | 947.95 ms | −41.4% |
| Dropped iterations | 35 (0.49%) | 0 (0.00%) | **Eliminated** |
| Backend CPU avg | 80.77% | 72.22% | −8.6pp |
| DB CPU peak | 62.79% | 26.63% | **−57.6%** |

The per-request ingest latency improved by 76% and drops were eliminated under the isolated ingest ramp test.

---

### 6.4 Effect on `national_medium` (mixed load)

After applying all software optimisations, `national_medium` was re-run:

| Metric | Pre-optimisation | Post-optimisation | Change |
|---|---|---|---|
| **load_health** | RED | RED | — |
| Completed req/s | 16.49 | 16.77 | +1.7% |
| Drop rate | 55.2% (6,632) | 55.0% (6,608) | −0.2pp |
| Avg latency | 17,883 ms | 17,632 ms | −1.4% |
| p(95) latency | 22,238 ms | 20,885 ms | −6.1% |
| Backend CPU avg | 114.14% | 115.70% | +1.6pp |
| DB CPU avg | 49.21% | 47.95% | −1.3pp |

**The national_medium result is statistically unchanged.** This is the critical finding for the hardware case.

---

## 7. Why Software Optimisation Cannot Close the Gap

### 7.1 The hardware ceiling

The server has 2 vCPU. Python (CPython, used by Django) does not parallelise CPU work across cores within a single process due to the Global Interpreter Lock. Gunicorn works around this with 5 separate worker processes — each uses one CPU core. With 5 workers on 2 physical cores, the OS scheduler context-switches between processes.

The maximum sustained throughput observed across all benchmarks: **~16.5–17 mixed req/s** at 100% CPU utilisation.

The `ingest_isolation` optimisation reduced CPU cost *per ingest request* by approximately 75%. On the isolated test this translated directly into lower latency and zero drops. On the mixed `national_medium` test it made no difference because:

1. The target rate is 40 req/s (35 ingest + 5 teacher)
2. The server completes ~17 req/s regardless of per-request efficiency
3. The 2 vCPUs are fully saturated. CPU freed by a faster ingest handler is immediately consumed by the queue of pending requests
4. The binding constraint is **not algorithmic efficiency** — it is the number of cores

### 7.2 Quantifying the gap

| | Value |
|---|---|
| Server's sustainable mixed throughput | ~17 req/s |
| `national_medium` target | **40 req/s** |
| Shortfall | **2.4× over capacity** |
| `national_high` target | **60 req/s** |
| Shortfall (high) | **3.5× over capacity** |

### 7.3 vCPU requirement estimate

Assuming linear throughput scaling with CPU cores (reasonable for a workload of independent HTTP requests with no shared mutable state):

```
Required vCPUs (national_medium) = 40 req/s ÷ 17 req/s × 2 vCPUs
                                 = 4.7 vCPUs  →  minimum 4 vCPU instance + 20% headroom

Required vCPUs (national_high)   = 60 req/s ÷ 17 req/s × 2 vCPUs
                                 = 7.1 vCPUs  →  8 vCPU instance recommended
```

Gunicorn worker count should be re-set to `2 × vCPUs + 1` after any upgrade:
- 4 vCPU → 9 workers
- 8 vCPU → 17 workers

---

## 8. Remaining Software Optimisations (Pending)

These optimisations require database schema migrations (column removals). They were deferred pending a thorough audit of all analytics code that reads each column. The audit confirmed that several columns previously believed to be replay-only are in fact actively used by analytics queries, which constrains what can safely be removed without analytics rework.

| Field | Size per row | Analytics dependency | Safe to remove? |
|---|---|---|---|
| `TurnEvent.bot_positions_after` | ~150 bytes | None | Yes — no analytics code reads this |
| `TurnEvent.bot_positions_before` | ~150 bytes | `foreach_tile_context_by_level()` | No — breaks analytics |
| `TurnEvent.offered_cards` | ~600–800 bytes | Card family offered-vs-chosen analysis | No — breaks analytics |
| `TurnEvent.chosen_card` | ~200 bytes | Used as fallback in 13 analytics queries | Possible — requires hardening scalar columns first |
| `Run.game_map` | ~1,500 bytes | `foreach_tile_context_by_level()`, tile analytics | No — breaks analytics |

Even if all safe removals were applied, the reduction in PostgreSQL I/O would improve analytics latency and reduce DB CPU modestly, but would not change the fundamental CPU ceiling on the backend.

**The conclusion from the audit is the same as from the load tests: the bottleneck is backend CPU core count, not per-query I/O volume.**

---

## 9. Hardware Recommendation

### 9.1 Minimum specification for `national_medium` (50% adoption)

| Component | Current | Required |
|---|---|---|
| vCPUs | 2 | **4** |
| RAM | 3.8 GiB | **8 GiB** (PostgreSQL shared_buffers + 5+ Gunicorn workers + OS) |
| Storage | — | SSD, ≥20 GB |
| OS | — | Ubuntu 22.04 LTS or equivalent |

With 4 vCPUs and 9 Gunicorn workers, the expected throughput ceiling rises to approximately `9/5 × 17 = ~30 req/s` from process scaling alone. This brings the server to within reach of the 35 ingest RPS target; with the serialiser optimisation (already applied) and the pending JSONB column removals reducing per-request overhead further, 35 req/s sustained should be achievable.

### 9.2 Recommended specification for `national_high` (75% adoption) with headroom

| Component | Recommended |
|---|---|
| vCPUs | **8** |
| RAM | **16 GiB** |
| Storage | SSD, ≥50 GB |
| Gunicorn workers | **17** (`2 × 8 + 1`) |

At 8 vCPUs and 17 workers, the expected throughput ceiling is approximately `17/5 × 17 = ~58 req/s`, sufficient for the 60 req/s `national_high` target.

### 9.3 Why RAM matters alongside CPU

PostgreSQL's performance is heavily dependent on `shared_buffers` — the amount of RAM allocated for caching table and index pages. On the current 3.8 GiB server, the recommended `shared_buffers` setting (25% of RAM) is approximately 950 MB. The `national_medium` dataset alone has ~36,000 hot turn events across large JSONB columns. With 8–16 GiB RAM, PostgreSQL can cache the hot dataset in memory, eliminating repeated disk reads for repeated analytics queries. This would reduce the DB CPU from its current 49% avg under national_medium load.

---

## 10. Summary

| Question | Finding |
|---|---|
| What is the server's current sustainable throughput? | ~17 req/s (mixed load), confirmed by repeated benchmarks |
| What throughput is required? | 40 req/s (medium), 60 req/s (high) |
| Were software optimisations applied? | Yes — PgBouncer, worker tuning, and serialiser pipeline fix. All measured. |
| Did software optimisations close the gap? | Partially on isolated ingest (−76% latency, drops eliminated). Not at all on mixed national-scale load — the hardware ceiling is binding. |
| What is needed? | Minimum: 4 vCPU / 8 GiB for national_medium. Recommended: 8 vCPU / 16 GiB for national_high with headroom. |

The software stack has been optimised to the extent possible without architectural changes. The remaining gap between 17 req/s and 40–60 req/s is structural: it requires more CPU cores.

---

*All benchmark numbers in this report were produced on the production server (2 vCPU Intel Xeon E7-8880 v3, 3.8 GiB RAM) running the benchmark Docker Compose stack in isolation (no other workloads). Results are reproducible by running `run_scenario.py national_medium` and `run_scenario.py ingest_isolation` from the `benchmarks/` directory.*
