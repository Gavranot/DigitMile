# Comparison: PgBouncer ON vs PgBouncer OFF

- **Before:** `/var/www/digitmile/benchmarks/server_reports/national_medium_with_pgbouncer.json` (scenario `national_medium`)
- **After:**  `/var/www/digitmile/benchmarks/server_reports/national_medium.json` (scenario `national_medium`)

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | green | green | — |
| http_reqs.rate (sustained RPS) | 15.90 | 15.93 | +0.2% |
| http_req_duration.avg | 47.28 ms | 29.00 ms | -38.7% |
| http_req_duration.p(95) | 133.38 ms | 101.98 ms | -23.5% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | — | — | — |
| iterations.count (completed) | 4804 | 4805 | 0.0% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 46.19% | 30.03% | -35.0% |
| cpu_percent_peak | 117.72% | 119.54% | +1.5% |
| memory_usage_bytes_peak | 372768768.00 | 376963072.00 | +1.1% |

## Pipeline & resources

Surfaces what the HTTP-side latency table can't show: how the async write
path (flusher), the database, and Redis behave under the same workload.

### Backend container

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 46.19% | 30.03% | -35.0% |
| cpu_percent_peak | 117.72% | 119.54% | +1.5% |
| memory_usage_bytes_avg | 349766054.81 | 360344833.65 | +3.0% |
| memory_usage_bytes_peak | 372768768.00 | 376963072.00 | +1.1% |

### Flusher (async write path)

Same workload should drive similar flusher CPU. Large gaps imply the
flusher is either backlogging (buffer growing) or starved (low CPU,
high backend pressure). Memory peak proxies how deep the buffer got.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 12.36% | 13.02% | +5.3% |
| cpu_percent_peak | 14.97% | 14.95% | -0.1% |
| memory_usage_bytes_peak | 81652613.12 | 87629496.32 | +7.3% |

### Database (PostgreSQL)

Reflects how much real write work the flusher pushed to PG. Higher db CPU
with the same HTTP throughput is *good* — more rows actually committed.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 19.98% | 21.53% | +7.8% |
| cpu_percent_peak | 89.58% | 114.68% | +28.0% |

### Redis throughput

`total_commands_processed` delta is a proxy for end-to-end pipeline activity:
LPUSH from the HTTP path + LRANGE/LTRIM from the flusher + cache GETs/SETs.
Higher = more data moved through the full ingest path in the same window.

| Metric | Before | After | Δ |
|---|---|---|---|
| total_commands_processed (Δ during run) | 24052 | 25510 | +6.1% |
| cache hits | 3666 | 3942 | +7.5% |
| cache misses | 2347 | 2432 | +3.6% |
| cache hit_rate_pct | 61.00% | 61.80% | +1.3% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 112.31 ms | 100.41 ms | -10.6% |
| pre_benchmark.classroom_dashboard_summaries avg | 13.00 ms | 13.16 ms | +1.2% |
| pre_benchmark.student_dashboard_summaries avg | 519.12 ms | 496.21 ms | -4.4% |
| pre_benchmark.turn_insights_payload avg | 85.54 ms | 98.92 ms | +15.6% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 68.46 ms | 79.05 ms | +15.5% |
| post_benchmark.classroom_dashboard_summaries avg | 16.33 ms | 12.94 ms | -20.8% |
| post_benchmark.student_dashboard_summaries avg | 521.12 ms | 504.79 ms | -3.1% |
| post_benchmark.turn_insights_payload avg | 84.09 ms | 94.97 ms | +12.9% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
