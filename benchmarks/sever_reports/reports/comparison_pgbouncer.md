# Comparison: No PgBouncer vs With PgBouncer

- **Before:** `benchmarks/reports/before_pgbouncer_ingest_isolation.json` (scenario `before_pgbouncer_ingest_isolation`)
- **After:**  `benchmarks/reports/ingest_isolation.json` (scenario `ingest_isolation`)

## Toggle state

- Before overlays: `['no-pgbouncer.yml']`, image ref: `tree HEAD`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | green | yellow | — |
| http_reqs.rate (sustained RPS) | 29.76 | 29.14 | -2.1% |
| http_req_duration.avg | 10.66 ms | 412.88 ms | +3771.4% |
| http_req_duration.p(95) | 23.47 ms | 1829.56 ms | +7696.4% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | — | 86 | — |
| iterations.count (completed) | 7199 | 7113 | -1.2% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 29.35% | 56.28% | +91.8% |
| cpu_percent_peak | 76.51% | 99.40% | +29.9% |
| memory_usage_bytes_peak | 307861913.60 | 310693068.80 | +0.9% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 37.63 ms | 27.02 ms | -28.2% |
| pre_benchmark.classroom_dashboard_summaries avg | 7.35 ms | 6.17 ms | -16.1% |
| pre_benchmark.student_dashboard_summaries avg | 522.54 ms | 542.55 ms | +3.8% |
| pre_benchmark.turn_insights_payload avg | 56.23 ms | 35.06 ms | -37.6% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 47.68 ms | 48.84 ms | +2.4% |
| post_benchmark.classroom_dashboard_summaries avg | 7.21 ms | 7.43 ms | +3.1% |
| post_benchmark.student_dashboard_summaries avg | 1247.32 ms | 1283.25 ms | +2.9% |
| post_benchmark.turn_insights_payload avg | 43.90 ms | 46.22 ms | +5.3% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
