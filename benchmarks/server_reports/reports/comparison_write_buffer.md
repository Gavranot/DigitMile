# Comparison: Synchronous ingest vs Redis-buffered ingest

- **Before:** `benchmarks/reports/before_write_buffer_ingest_isolation.json` (scenario `before_write_buffer_ingest_isolation`)
- **After:**  `benchmarks/reports/ingest_isolation.json` (scenario `ingest_isolation`)

## Toggle state

- Before overlays: `['no-flusher.yml']`, image ref: `baseline/pre-write-buffer`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | yellow | yellow | — |
| http_reqs.rate (sustained RPS) | 28.67 | 29.14 | +1.7% |
| http_req_duration.avg | 811.69 ms | 412.88 ms | -49.1% |
| http_req_duration.p(95) | 3563.96 ms | 1829.56 ms | -48.7% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | 177 | 86 | -51.4% |
| iterations.count (completed) | 7022 | 7113 | +1.3% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 70.53% | 56.28% | -20.2% |
| cpu_percent_peak | 121.00% | 99.40% | -17.9% |
| memory_usage_bytes_peak | 283639808.00 | 310693068.80 | +9.5% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 27.79 ms | 27.02 ms | -2.8% |
| pre_benchmark.classroom_dashboard_summaries avg | 13.87 ms | 6.17 ms | -55.5% |
| pre_benchmark.student_dashboard_summaries avg | 636.23 ms | 542.55 ms | -14.7% |
| pre_benchmark.turn_insights_payload avg | 34.93 ms | 35.06 ms | +0.4% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 47.69 ms | 48.84 ms | +2.4% |
| post_benchmark.classroom_dashboard_summaries avg | 23.02 ms | 7.43 ms | -67.7% |
| post_benchmark.student_dashboard_summaries avg | 1439.49 ms | 1283.25 ms | -10.9% |
| post_benchmark.turn_insights_payload avg | 48.98 ms | 46.22 ms | -5.6% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
