# Benchmark Pipeline

This directory contains the benchmark tooling for DigitMile's backend load testing.

## Layout

- `benchmarks/k6/` - k6 workload scripts for ingest, dashboard, replay, and mixed weekly-cycle traffic
- `benchmarks/scenarios/` - JSON scenario definitions controlling dataset size, traffic shape, and report output
- `benchmarks/reports/` - generated reports; ignored by git except for `.gitignore`
- `benchmarks/run_scenario.py` - orchestrates dataset preparation, k6 traffic, compaction, verification, and report generation

## Prerequisites

- Docker available on the host machine
- a local `digitmile-backend:latest` image available; if missing, `benchmarks/run_scenario.py` will build it once via `docker compose build backend`
- benchmark teachers created by `prepare_benchmark_dataset` use password `benchmark_password_123`
- each scenario runs in its own isolated Docker Compose stack defined in `benchmarks/docker-compose.benchmark.yml`
- the isolated stack includes its own `benchmark-db` PostgreSQL container and `benchmark-backend` Django container, so benchmark runs do not touch the development database
- benchmark traffic runs inside a standalone persistent `grafana/k6` Docker container attached directly to the benchmark stack network
- the default scenario path targets `http://benchmark-backend:8000` from inside that network and sends `Host: localhost`
- set `BENCHMARK_KEEP_STACK=1` before running a scenario to keep the containers alive after a failure for debugging

## Scenario tiers

The scenarios are organized in tiers that answer different questions.
Run them in order: Tier 1 first, then Tier 2, then Tier 3.

### Tier 1 — Realistic baseline: `realistic_school_day`

**Question: Can the server handle typical school-day traffic without struggling?**

- Dataset: 1 teacher, 3 classrooms, 20 students = 60 students; 8 weeks history (6 cold, 2 hot)
- Traffic: 1 req/sec per traffic class = 5 req/sec total; 3-minute run
- Expected outcome: `load_health: "green"`, all checks pass, 0 dropped iterations
- If this scenario shows drops or high latency, the problem needs to be fixed at the application
  level before stress testing is useful

This is the most important scenario for production readiness. Run it first.

### Tier 2 — Break-point finder: `stress_ramp`

**Question: At what traffic level does the server start struggling?**

- Dataset: 2 teachers, 4 classrooms each, 25 students = 200 students; 10 weeks (8 cold, 2 hot)
- Traffic: ramps from 0 to peak rates over 5 minutes using `ramping-arrival-rate`
- Peak rates: 8 ingest/sec, 4 dashboard/sec, 3 analytics/sec, 2 turn_insights/sec, 2 replay/sec
- Expected outcome: early minutes are green, drops appear toward the end of the ramp
- The inflection point where latency climbs and drops first appear is the server's headroom ceiling

### Tier 3 — Friday compaction: `compaction_under_read_load`

**Question: Does end-of-week compaction produce correct rollup data after real school-day activity?**

- Dataset: 2 teachers, 2 classrooms, 10 students; 6 weeks (4 cold, 2 hot)
- Traffic: 2 minutes of realistic mixed load (same rates as Tier 1)
- After traffic: compacts week 5 and runs `verify_weekly_rollups`; compares pre/post analytics latency
- Expected outcome: compaction succeeds, verification passes, post-traffic analytics remain fast

### Other scenarios

| Scenario | Purpose |
|---|---|
| `hot_only_small` | Fast smoke test after code changes; not a load test |
| `bag_conditional_compaction_smoke` | Validates bag-conditional rollup logic; not a load test |
| `hot_week_read_write_heavy` | Historical heavy stress; `load_health` will be red; use only for raw throughput exploration |
| `mixed_semester_medium/heavy` | Full-semester scale tests; use after Tier 1 and 2 are understood |
| `retry_storm_ingest` | Ingest retry and idempotency validation |
| `ingest_isolation` | Find the ingest throughput ceiling before running national scenarios |
| `lesson_bell` | Burst-regime scenario: 10s ramp + 60s hold at peak + 30s drain; models classroom synchronisation at end of IT period |

## National-scale scenarios

These scenarios are derived from the North Macedonia national load model and represent the
production readiness targets for full-country deployment. They are **not pass/fail tests** —
with a 3-worker Gunicorn setup they will produce `load_health: "red"`. The purpose is to
quantify the gap so you know what you need to scale to.

### The load model

DigitMile has an asymmetric traffic profile:

- **Students** only generate ingest traffic — exactly one API call per completed Run. No heartbeats, no per-turn submissions, no leaderboard polling.
- **Teachers** generate all read traffic — dashboard reloads, analytics, turn_insights.

**Canonical formula reference:** `docs/research/ingest-capacity-model.md`. Open that doc to change input parameters (adoption, attendance, mean turns, wall-time per turn, clustering, burst window) and recalculate every downstream metric. The summary below is a copy of its §7 base scenarios for quick reference.

| Adoption | Peak concurrent students (CCU) | Steady ingest RPS | Lesson-bell burst RPS (60s) | Peak concurrent teachers | Dashboard RPS |
|----------|--------------------------------|-------------------|------------------------------|--------------------------|---------------|
| Medium 50% | ~4,243 | **~11** | **~29** | ~80 | ~2 |
| High 75%   | ~6,365 | **~16** | **~44** | ~120 | ~3 |

Two distinct load regimes matter:

1. **Steady-state** (`national_medium` / `national_high`) — sustained ~11–16 RPS over the busy 10–15 min window. Each ingest carries a full Run payload (~15.5 KB with `T=20`), so per-request CPU is the binding cost, not RPS.
2. **Lesson-bell burst** (`lesson_bell`) — ~29–44 RPS for ~60 s as classrooms finish their final Run before the bell. The Redis write buffer absorbs the spike; PG never sees the peak directly. Stage profile is 10 s ramp + 60 s hold + 30 s drain; bump `ingest_rate_per_sec` from 29 → 44 for the high-adoption variant.

Run `ingest_isolation` before either set to find the raw ingest ceiling on the current hardware.

### Run order for national scenarios

```bash
# Step 1 — find the ingest ceiling (required before national scenarios)
python benchmarks/run_scenario.py benchmarks/scenarios/ingest_isolation.json

# Step 2 — medium adoption target (expected red with current infra)
python benchmarks/run_scenario.py benchmarks/scenarios/national_medium.json

# Step 3 — high adoption target (expected red; run only after medium is understood)
python benchmarks/run_scenario.py benchmarks/scenarios/national_high.json
```

### How to interpret a red national scenario

A red result is the expected and correct result with the current single-instance setup.
Do not reduce rates — that defeats the purpose. Instead read:

1. **`dropped_iterations` count and rate** — this tells you how many of the intended 35 (or 52)
   RPS the server actually kept up with. If 80% are dropped at 35 ingest/sec, you need roughly
   5× the current ingest capacity.

2. **`completed_iterations` latency** — the requests that did complete tell you the per-request
   cost under saturation. If avg ingest latency under load is 400ms, you need
   `ceil(target_rps × 0.4)` concurrent workers for ingest alone.

3. **`resource_summary` CPU** — if the backend container is at 100% CPU throughout, the
   bottleneck is compute (more workers or faster queries). If CPU is below 50% with heavy drops,
   the bottleneck is likely DB connection pool exhaustion or lock contention.

4. **`pre_benchmark` analytics latency** — this is independent of load. If `turn_insights_payload`
   is already above 5 seconds at idle with 1,000+ students in the dataset, that is an
   application-level query problem that exists regardless of traffic volume.

### What would make these scenarios green

- **Ingest**: the endpoint is a single atomic transaction with bulk inserts. Each request is
  independent and parallelises well. Adding Gunicorn workers directly scales ingest throughput.
  Rule of thumb: `workers_needed ≈ target_ingest_rps × ingest_latency_seconds`.
- **Analytics / turn_insights**: these are read-heavy aggregate queries over rollup tables.
  They do not benefit from more workers beyond a few (DB becomes the bottleneck). The path
  to improvement is query optimisation, appropriate indexes, or a Redis read cache.
- **Connection pool**: with many workers each holding a DB connection, ensure `CONN_MAX_AGE`
  and PgBouncer (or equivalent) are configured to avoid connection exhaustion.

## Running a scenario

```bash
# Tier 1 — always run this first
python benchmarks/run_scenario.py benchmarks/scenarios/realistic_school_day.json

# Tier 2 — run after Tier 1 is green
python benchmarks/run_scenario.py benchmarks/scenarios/stress_ramp.json

# Tier 3 — validate Friday compaction
python benchmarks/run_scenario.py benchmarks/scenarios/compaction_under_read_load.json

# National: ingest ceiling (run before national_medium/national_high)
python benchmarks/run_scenario.py benchmarks/scenarios/ingest_isolation.json

# National: medium adoption (35 ingest RPS — expected red with current infra)
python benchmarks/run_scenario.py benchmarks/scenarios/national_medium.json

# National: high adoption (52 ingest RPS — expected red; run after medium is understood)
python benchmarks/run_scenario.py benchmarks/scenarios/national_high.json
```

Each run will:

1. create an isolated PostgreSQL + Django benchmark stack
2. wait for the backend health check
3. seed benchmark data (`prepare_benchmark_dataset`)
4. run a pre-traffic analytics baseline (`benchmark_teacher_analytics`)
5. run k6 traffic with live `docker stats` sampling
6. optionally run compaction and verification
7. run a post-traffic analytics baseline
8. write a full JSON report and tear down the isolated stack

## How to read a report

Every scenario produces a JSON report at the path specified by `report_output` in the
scenario config. Open `benchmarks/reports/<scenario_name>.json` to inspect it.

### Step 1 — Start with `load_health`

```json
"load_health": "green"
```

This is the first field in every report and is the single most important signal.

| Value | Meaning |
|---|---|
| `"green"` | Zero drops, zero check failures. Latency numbers are reliable. |
| `"yellow"` | Up to 5% drops or 2% check failures. Results are usable but optimistic. |
| `"red"` | Server over capacity. Latency numbers are **not representative**. Reduce rates. |

**If `load_health` is `"red"`, stop reading latency numbers from this run.** They only
cover the requests that happened to get through and will look artificially fast compared
to what the server would return at a sustainable rate.

The previous heavy scenario reports (`hot_week_read_write_heavy*`) are red. The reported
22-second average latency and 856 dropped iterations mean the server was overwhelmed and
46% of the intended traffic was discarded before it even started. Those numbers cannot be
used to assess production readiness.

Each script result inside `k6_summaries[n].load_health` has the same field plus a
human-readable `note` explaining exactly what was found.

### Step 2 — Check `dropped_iterations`

```json
"highlights": {
  "dropped_iterations": { "count": 0, "rate": 0.0 },
  ...
}
```

`dropped_iterations` is how many requests k6 planned to send but could not, because all
VUs were busy waiting for the server to respond. It is **not the same as failed requests**.

- `count: 0` — the server kept up; latency numbers are meaningful
- `count > 0` — the server fell behind; latency numbers only cover the requests that got
  in and are optimistic, because the slowest requests never started

### Step 3 — Read latency from `http_req_duration` (only when health is green or yellow)

```json
"http_req_duration": {
  "avg": 312.4,
  "p(90)": 890.1,
  "p(95)": 1240.3,
  "min": 18.2,
  "max": 2100.5
}
```

All values are in **milliseconds**.

- `avg` — mean response time across all completed requests
- `p(90)` — 90% of requests completed faster than this
- `p(95)` — 95% of requests completed faster than this; use this as the headline figure

For the teacher dashboard to feel responsive, aim for p95 under 3000ms (3 seconds) at
realistic load. The `turn_insights` section is typically the slowest; address it as an
application-level query optimization problem if it dominates.

### Step 4 — Read `checks` to see which endpoint types passed

```json
"checks": {
  "passes": 992,
  "fails": 0,
  "by_check": {
    "mixed open-week ingest accepted":  { "passes": 276, "fails": 0 },
    "mixed dashboard ok":               { "passes": 215, "fails": 0 },
    "mixed analytics ok":               { "passes": 204, "fails": 0 },
    "mixed turn insights ok":           { "passes": 202, "fails": 0 },
    "mixed replay ok":                  { "passes": 95,  "fails": 0 }
  }
}
```

Each check maps to one endpoint group. Fails mean the server returned an unexpected HTTP
status (5xx, 403, or similar). A `409 Conflict` on an ingest request is an expected
closed-week rejection, not a failure — this is why the checks (`mixed open-week ingest
accepted`) are more meaningful than `http_req_failed`, which counts 4xx as failures.

### Step 5 — Read the pre-benchmark analytics baseline

```json
"pre_benchmark": {
  "measurements_ms": {
    "turn_insights_payload":       { "avg": 2924, "p95": 3117 },
    "analytics_payload":           { "avg": 593,  "p95": 716  },
    "student_dashboard_summaries": { "avg": 927,  "p95": 963  }
  }
}
```

These come from `benchmark_teacher_analytics` running against the isolated backend
**before** k6 traffic starts. They represent the server's idle cost at the given dataset
size and are independent of load and dropped iterations.

Use them to:
- understand which endpoint is the bottleneck before any traffic is applied
- compare across different dataset sizes (more students = slower)
- compare pre vs post to see whether compaction improved or degraded query performance

`turn_insights_payload` is almost always the slowest. On your development machine at
~2.9 seconds idle, the same query will be noticeably slower on a weaker production server.
If the pre-benchmark shows `turn_insights` over 5 seconds at idle, teachers will see that
section loading slowly regardless of load test results — that is an application-level
query problem, not a load problem.

### Step 6 — Read `resource_summary` to see actual server pressure

```json
"resource_summary": {
  "benchmark-backend-1": {
    "cpu_percent_avg": 42.1,
    "cpu_percent_peak": 89.3,
    "memory_usage_bytes_avg": 134217728,
    "memory_usage_bytes_peak": 201326592
  }
}
```

Sampled from `docker stats` every N seconds during the k6 traffic window.

- CPU peak below 30% — traffic rates were too low to be a meaningful stress test
- CPU sustained at 50–80% — good stress; you have real data about server behavior under load
- CPU pegged at 100% throughout — server was saturated; this correlates with red `load_health`

### Step 7 — For `stress_ramp` runs: look at shape, not just totals

In a ramp run, all rates increase from 0 to the configured peak over the full duration.
Early in the run latency is fast and drops are zero. The server's ceiling is wherever
drops first appear and latency starts climbing. The overall `dropped_iterations` count
and `load_health` tell you whether the ceiling was hit before or at the peak rate:

- `load_health: "green"` — the server handled the full peak rate; headroom exists above it
- `load_health: "red"` — the ceiling is somewhere below the peak rate; reduce peak and re-run
  to narrow down the threshold

## Calibrating results to your production server

Your development machine is faster than the production host. The idle analytics numbers
in `pre_benchmark` reflect your machine's performance, not the server's.

To estimate production performance:

1. Run `realistic_school_day` on your dev machine and record `pre_benchmark.measurements_ms`
2. On the production server (or a server-like VM), run:
   ```bash
   docker exec "digitmile-backend" python manage.py prepare_benchmark_dataset \
     --teachers 1 --classrooms-per-teacher 3 --students-per-classroom 20 \
     --weeks 8 --runs-per-student-per-week 3 --avg-turns-per-run 6 \
     --card-mix-profile balanced --bag-level-ratio 0.35 \
     --compact-weeks 1-6 --hot-weeks 2 --anchor-week-start 2026-03-09 \
     --output /tmp/prod-dataset.json
   docker exec "digitmile-backend" python manage.py benchmark_teacher_analytics \
     <teacher_id> --iterations 5 --output /tmp/prod-baseline.json
   ```
3. Compare `prod-baseline.json` vs the dev `pre_benchmark` to get the slowdown ratio
4. Apply that ratio to the load test latency numbers to estimate production behavior

The most reliable cross-environment signal is whether `load_health` stays green at
`realistic_school_day` rates on the production server.

## Scenario report contents

Each scenario report includes:

- `load_health` — top-level green/yellow/red indicator
- `scenario_config` — the full scenario JSON that was used
- `scenario_summary` — compose project, scripts, duration, URLs, synthetic reference time
- `dataset_report` — counts, week layout, hot/cold split, ingest/replay targets, synthetic clock
- `pre_benchmark` — idle analytics baseline before traffic
- `k6_summaries` — per-script results: highlights, checks, load_health, resource_summary
- `resource_summary` — aggregated CPU/memory stats across all k6 scripts
- `compaction_result` — compaction stdout and duration when configured (compact_weekly_runs runs verify_weekly_rollups internally before deleting raw rows, so a successful exit code is the verification verdict)
- `post_benchmark` — idle analytics baseline after traffic and optional compaction

## Redis policy

Redis caching is intentionally not enabled by this benchmark pipeline. Baseline reports
must exist first, and Redis should only be added after those reports prove a meaningful
read-latency improvement is needed.

## Optimization toggles (thesis before/after measurements)

Two scenario JSON fields let any scenario run against a pre-optimization
state of the system without modifying production code paths:

- **`compose_overlays`** — list of overlay filenames under `benchmarks/overlays/`.
  Each overlay reverts one in-tree architectural optimization (PgBouncer, PG
  tuning, query cache). See `benchmarks/overlays/README.md` for the table.
- **`benchmark_image_ref`** — any git ref (tag, branch, or SHA). The backend
  image used by the benchmark stack is built from that commit via a worktree
  under `.baseline-worktrees/` (gitignored, reused across runs).

The three baseline tags below mark the predecessor commits of the
architectural optimizations whose pre-optimization code was deleted in-tree
and therefore cannot be reverted via overlay:

| Tag | Maps to | Reverts |
|---|---|---|
| `baseline/pre-rollup-analytics` | `22c9bfc^` | C — hot-data analytics removal |
| `baseline/pre-ninja` | `6d77836^` | E — django-ninja + Pydantic ingest |
| `baseline/pre-write-buffer` | `e27b758^` | F — Redis-buffered ingest + flusher |

Example "before optimization F" scenario fragment:

```json
{
  "benchmark_image_ref": "baseline/pre-write-buffer",
  "compose_overlays": []
}
```

Example "before A + B + D" (the three in-tree overlay-reversible ones):

```json
{
  "compose_overlays": ["no-pgbouncer.yml", "pg-defaults.yml", "dummy-cache.yml"]
}
```

Both fields are optional. Scenarios that set neither run against the current
tree, which is the existing behaviour. None of this machinery affects
production: overlays live only under `benchmarks/`, baseline images are
tagged `digitmile-benchmark-backend:baseline-…`, and the settings.py knobs
they rely on (`DJANGO_CACHE_BACKEND`, `DB_CONN_MAX_AGE`,
`DB_DISABLE_SERVER_SIDE_CURSORS`) default to current production values when
unset.

Baseline images for `benchmark_image_ref` may not always boot cleanly — older
commits can carry incompatible management-command signatures or schema
expectations relative to the harness. Validate each baseline once before
relying on it for thesis numbers.

### Global PgBouncer toggle: `BENCHMARK_DISABLE_PGBOUNCER`

Set the env var to force `no-pgbouncer.yml` into every scenario's overlay set
for the duration of a shell session. Lets you re-run every comparison without
PgBouncer in the stack without editing any scenario JSON. Reports land under
`benchmarks/reports/no_pgbouncer/` so the two sets of numbers don't collide.

```bash
# Sweep the full comparison set without PgBouncer
export BENCHMARK_DISABLE_PGBOUNCER=1

python benchmarks/run_scenario.py benchmarks/scenarios/ingest_isolation.json
python benchmarks/run_scenario.py benchmarks/scenarios/before_pg_tuning_ingest_isolation.json
python benchmarks/run_scenario.py benchmarks/scenarios/before_query_cache_realistic_school_day.json
python benchmarks/run_scenario.py benchmarks/scenarios/before_write_buffer_ingest_isolation.json
# (etc.)

# Switch back to the standard with-PgBouncer set
unset BENCHMARK_DISABLE_PGBOUNCER
python benchmarks/run_scenario.py benchmarks/scenarios/ingest_isolation.json
```

Scenarios that already include `no-pgbouncer.yml` are deduped automatically —
no harm in setting the env var across a sweep that includes
`before_pgbouncer_ingest_isolation.json`. The verification banner shows the
final overlay list so you can confirm the toggle landed.

### Running baseline scenarios on hosts without git

The deployment server is not a git checkout — `git rev-parse` fails, and
`benchmark_image_ref` therefore cannot resolve to a SHA. Use the
`benchmark_image` field instead, which names a Docker image directly:

```json
{
  "benchmark_image_ref": "baseline/pre-write-buffer",
  "benchmark_image":     "gashmurble/digitmile-baseline:pre-write-buffer",
  "compose_overlays":    ["no-flusher.yml"],
  ...
}
```

When both fields are present, `benchmark_image` wins and no git work runs.
The ref stays in the JSON for documentation.

To produce the registry image:

```bash
# On a local dev box where git is available — one-time per baseline
python benchmarks/run_scenario.py benchmarks/scenarios/baseline_smoke_pre_write_buffer.json
# This builds digitmile-benchmark-backend:baseline-baseline-pre-write-buffer-<sha12>

docker tag \
    digitmile-benchmark-backend:baseline-baseline-pre-write-buffer-6d7783658a6f \
    gashmurble/digitmile-baseline:pre-write-buffer
docker push gashmurble/digitmile-baseline:pre-write-buffer
```

On the server, compose will pull automatically on first `up`:

```bash
python3 benchmarks/run_scenario.py benchmarks/scenarios/before_write_buffer_ingest_isolation.json
```

The image-verification banner will still print `mode: baseline` and the
SHA captured in the image tag, so the report continues to prove which
commit produced the numbers.
