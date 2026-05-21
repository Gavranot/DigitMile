# Comparison: Stock PG vs Tuned PG

- **Before:** `benchmarks/reports/before_pg_tuning_ingest_isolation.json` (scenario `before_pg_tuning_ingest_isolation`)
- **After:**  `benchmarks/reports/ingest_isolation.json` (scenario `ingest_isolation`)

## Toggle state

- Before overlays: `['pg-defaults.yml']`, image ref: `tree HEAD`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | yellow | yellow | — |
| http_reqs.rate (sustained RPS) | 29.06 | 29.14 | +0.3% |
| http_req_duration.avg | 412.49 ms | 412.88 ms | +0.1% |
| http_req_duration.p(95) | 2016.82 ms | 1829.56 ms | -9.3% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | 103 | 86 | -16.5% |
| iterations.count (completed) | 7096 | 7113 | +0.2% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 52.54% | 56.28% | +7.1% |
| cpu_percent_peak | 101.84% | 99.40% | -2.4% |
| memory_usage_bytes_peak | 308386201.60 | 310693068.80 | +0.7% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 27.80 ms | 27.02 ms | -2.8% |
| pre_benchmark.classroom_dashboard_summaries avg | 6.07 ms | 6.17 ms | +1.6% |
| pre_benchmark.student_dashboard_summaries avg | 541.00 ms | 542.55 ms | +0.3% |
| pre_benchmark.turn_insights_payload avg | 34.90 ms | 35.06 ms | +0.5% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 42.88 ms | 48.84 ms | +13.9% |
| post_benchmark.classroom_dashboard_summaries avg | 7.00 ms | 7.43 ms | +6.1% |
| post_benchmark.student_dashboard_summaries avg | 1245.32 ms | 1283.25 ms | +3.0% |
| post_benchmark.turn_insights_payload avg | 41.76 ms | 46.22 ms | +10.7% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
