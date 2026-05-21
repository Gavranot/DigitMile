# Comparison: With PGBouncer vs Without PGBouncer

- **Before:** `benchmarks/sever_reports/reports/ingest_isolation.json` (scenario `ingest_isolation`)
- **After:**  `benchmarks/sever_reports/reports/nopgbouncer_ingest_isolation.json` (scenario `ingest_isolation`)

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | yellow | green | — |
| http_reqs.rate (sustained RPS) | 29.14 | 29.80 | +2.2% |
| http_req_duration.avg | 412.88 ms | 10.73 ms | -97.4% |
| http_req_duration.p(95) | 1829.56 ms | 25.05 ms | -98.6% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | 86 | — | — |
| iterations.count (completed) | 7113 | 7199 | +1.2% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 56.28% | 28.63% | -49.1% |
| cpu_percent_peak | 99.40% | 72.16% | -27.4% |
| memory_usage_bytes_peak | 310693068.80 | 306603622.40 | -1.3% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 27.02 ms | 34.82 ms | +28.9% |
| pre_benchmark.classroom_dashboard_summaries avg | 6.17 ms | 7.11 ms | +15.2% |
| pre_benchmark.student_dashboard_summaries avg | 542.55 ms | 514.59 ms | -5.2% |
| pre_benchmark.turn_insights_payload avg | 35.06 ms | 42.91 ms | +22.4% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 48.84 ms | 50.05 ms | +2.5% |
| post_benchmark.classroom_dashboard_summaries avg | 7.43 ms | 6.91 ms | -7.0% |
| post_benchmark.student_dashboard_summaries avg | 1283.25 ms | 1225.95 ms | -4.5% |
| post_benchmark.turn_insights_payload avg | 46.22 ms | 46.43 ms | +0.5% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
