# Comparison: Dummy cache vs Redis cache

- **Before:** `benchmarks/reports/before_query_cache_realistic_school_day.json` (scenario `before_query_cache_realistic_school_day`)
- **After:**  `benchmarks/reports/realistic_school_day.json` (scenario `realistic_school_day`)

## Toggle state

- Before overlays: `['dummy-cache.yml']`, image ref: `tree HEAD`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | green | green | — |
| http_reqs.rate (sustained RPS) | 4.98 | 4.97 | -0.2% |
| http_req_duration.avg | 238.07 ms | 194.95 ms | -18.1% |
| http_req_duration.p(95) | 928.97 ms | 862.90 ms | -7.1% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | — | — | — |
| iterations.count (completed) | 903 | 905 | +0.2% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 53.76% | 47.05% | -12.5% |
| cpu_percent_peak | 109.25% | 103.07% | -5.7% |
| memory_usage_bytes_peak | 313419366.40 | 318242816.00 | +1.5% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 36.98 ms | 38.09 ms | +3.0% |
| pre_benchmark.classroom_dashboard_summaries avg | 8.42 ms | 8.58 ms | +1.9% |
| pre_benchmark.student_dashboard_summaries avg | 598.27 ms | 584.75 ms | -2.3% |
| pre_benchmark.turn_insights_payload avg | 49.28 ms | 46.21 ms | -6.2% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 34.22 ms | 37.88 ms | +10.7% |
| post_benchmark.classroom_dashboard_summaries avg | 8.48 ms | 8.58 ms | +1.2% |
| post_benchmark.student_dashboard_summaries avg | 589.56 ms | 594.54 ms | +0.8% |
| post_benchmark.turn_insights_payload avg | 44.50 ms | 44.53 ms | +0.1% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
