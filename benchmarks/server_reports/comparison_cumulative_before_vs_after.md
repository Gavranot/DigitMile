# Comparison: Pre-everything baseline (A+B+D+F reverted) vs Current tree (no PgBouncer)

- **Before:** `/var/www/digitmile/benchmarks/server_reports/before_all_optimizations.json` (scenario `before_all_optimizations`)
- **After:**  `/var/www/digitmile/benchmarks/server_reports/national_medium.json` (scenario `national_medium`)

## Toggle state

- Before overlays: `['no-pgbouncer.yml', 'pg-defaults.yml', 'dummy-cache.yml', 'no-flusher.yml']`, image ref: `baseline/pre-write-buffer`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | red | green | — |
| http_reqs.rate (sustained RPS) | 11.81 | 15.93 | +34.9% |
| http_req_duration.avg | 22683.68 ms | 29.00 ms | -99.9% |
| http_req_duration.p(95) | 29065.29 ms | 101.98 ms | -99.6% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | 920 | — | — |
| iterations.count (completed) | 3884 | 4805 | +23.7% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 78.25% | 30.03% | -61.6% |
| cpu_percent_peak | 114.89% | 119.54% | +4.0% |
| memory_usage_bytes_peak | 367106457.60 | 376963072.00 | +2.7% |

## Pipeline & resources

Surfaces what the HTTP-side latency table can't show: how the async write
path (flusher), the database, and Redis behave under the same workload.

### Backend container

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 78.25% | 30.03% | -61.6% |
| cpu_percent_peak | 114.89% | 119.54% | +4.0% |
| memory_usage_bytes_avg | 351216618.60 | 360344833.65 | +2.6% |
| memory_usage_bytes_peak | 367106457.60 | 376963072.00 | +2.7% |

### Flusher (async write path)

Same workload should drive similar flusher CPU. Large gaps imply the
flusher is either backlogging (buffer growing) or starved (low CPU,
high backend pressure). Memory peak proxies how deep the buffer got.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 0.00% | 13.02% | — |
| cpu_percent_peak | 0.00% | 14.95% | — |
| memory_usage_bytes_peak | 434176.00 | 87629496.32 | +20082.9% |

### Database (PostgreSQL)

Reflects how much real write work the flusher pushed to PG. Higher db CPU
with the same HTTP throughput is *good* — more rows actually committed.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 88.87% | 21.53% | -75.8% |
| cpu_percent_peak | 122.82% | 114.68% | -6.6% |

### Redis throughput

`total_commands_processed` delta is a proxy for end-to-end pipeline activity:
LPUSH from the HTTP path + LRANGE/LTRIM from the flusher + cache GETs/SETs.
Higher = more data moved through the full ingest path in the same window.

| Metric | Before | After | Δ |
|---|---|---|---|
| total_commands_processed (Δ during run) | 749 | 25510 | +3305.9% |
| cache hits | 393 | 3942 | +903.1% |
| cache misses | 137 | 2432 | +1675.2% |
| cache hit_rate_pct | 74.20% | 61.80% | -16.7% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 174.44 ms | 100.41 ms | -42.4% |
| pre_benchmark.classroom_dashboard_summaries avg | 46.25 ms | 13.16 ms | -71.5% |
| pre_benchmark.student_dashboard_summaries avg | 1135.55 ms | 496.21 ms | -56.3% |
| pre_benchmark.turn_insights_payload avg | 283.42 ms | 98.92 ms | -65.1% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 63.28 ms | 79.05 ms | +24.9% |
| post_benchmark.classroom_dashboard_summaries avg | 30.52 ms | 12.94 ms | -57.6% |
| post_benchmark.student_dashboard_summaries avg | 1126.49 ms | 504.79 ms | -55.2% |
| post_benchmark.turn_insights_payload avg | 80.81 ms | 94.97 ms | +17.5% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
