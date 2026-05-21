# Comparison: DummyCache (no query cache) vs django-redis query cache

- **Before:** `/var/www/digitmile/benchmarks/server_reports/before_query_cache_realistic_school_day.json` (scenario `before_query_cache_realistic_school_day`)
- **After:**  `/var/www/digitmile/benchmarks/server_reports/realistic_school_day.json` (scenario `realistic_school_day`)

## Toggle state

- Before overlays: `['dummy-cache.yml']`, image ref: `tree HEAD`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | green | green | — |
| http_reqs.rate (sustained RPS) | 4.98 | 4.99 | +0.1% |
| http_req_duration.avg | 88.92 ms | 46.67 ms | -47.5% |
| http_req_duration.p(95) | 177.59 ms | 98.14 ms | -44.7% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | — | — | — |
| iterations.count (completed) | 905 | 905 | 0.0% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 26.12% | 18.47% | -29.3% |
| cpu_percent_peak | 62.82% | 56.50% | -10.1% |
| memory_usage_bytes_peak | 317718528.00 | 320444825.60 | +0.9% |

## Pipeline & resources

Surfaces what the HTTP-side latency table can't show: how the async write
path (flusher), the database, and Redis behave under the same workload.

### Backend container

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 26.12% | 18.47% | -29.3% |
| cpu_percent_peak | 62.82% | 56.50% | -10.1% |
| memory_usage_bytes_avg | 302640005.12 | 304370155.52 | +0.6% |
| memory_usage_bytes_peak | 317718528.00 | 320444825.60 | +0.9% |

### Flusher (async write path)

Same workload should drive similar flusher CPU. Large gaps imply the
flusher is either backlogging (buffer growing) or starved (low CPU,
high backend pressure). Memory peak proxies how deep the buffer got.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 1.57% | 1.61% | +2.5% |
| cpu_percent_peak | 2.56% | 2.75% | +7.4% |
| memory_usage_bytes_peak | 61750640.64 | 61949870.08 | +0.3% |

### Database (PostgreSQL)

Reflects how much real write work the flusher pushed to PG. Higher db CPU
with the same HTTP throughput is *good* — more rows actually committed.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 6.35% | 3.13% | -50.7% |
| cpu_percent_peak | 13.84% | 7.98% | -42.3% |

### Redis throughput

`total_commands_processed` delta is a proxy for end-to-end pipeline activity:
LPUSH from the HTTP path + LRANGE/LTRIM from the flusher + cache GETs/SETs.
Higher = more data moved through the full ingest path in the same window.

| Metric | Before | After | Δ |
|---|---|---|---|
| total_commands_processed (Δ during run) | 8256 | 8924 | +8.1% |
| cache hits | 181 | 694 | +283.4% |
| cache misses | 1825 | 1875 | +2.7% |
| cache hit_rate_pct | 9.00% | 27.00% | +200.0% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 43.63 ms | 43.67 ms | +0.1% |
| pre_benchmark.classroom_dashboard_summaries avg | 9.17 ms | 9.33 ms | +1.7% |
| pre_benchmark.student_dashboard_summaries avg | 289.94 ms | 293.23 ms | +1.1% |
| pre_benchmark.turn_insights_payload avg | 57.74 ms | 53.23 ms | -7.8% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 39.32 ms | 38.64 ms | -1.7% |
| post_benchmark.classroom_dashboard_summaries avg | 8.72 ms | 8.91 ms | +2.2% |
| post_benchmark.student_dashboard_summaries avg | 286.26 ms | 292.61 ms | +2.2% |
| post_benchmark.turn_insights_payload avg | 48.21 ms | 47.20 ms | -2.1% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
