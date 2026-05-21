# Comparison: PG defaults vs PG tuned (sync_commit=off + tuning)

- **Before:** `/var/www/digitmile/benchmarks/server_reports/before_pg_tuning_ingest_isolation.json` (scenario `before_pg_tuning_ingest_isolation`)
- **After:**  `/var/www/digitmile/benchmarks/server_reports/ingest_isolation.json` (scenario `ingest_isolation`)

## Toggle state

- Before overlays: `['pg-defaults.yml']`, image ref: `tree HEAD`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | green | green | — |
| http_reqs.rate (sustained RPS) | 29.76 | 29.70 | -0.2% |
| http_req_duration.avg | 11.71 ms | 11.36 ms | -3.0% |
| http_req_duration.p(95) | 24.83 ms | 26.02 ms | +4.8% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | — | — | — |
| iterations.count (completed) | 7199 | 7199 | 0.0% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 27.47% | 28.80% | +4.8% |
| cpu_percent_peak | 83.44% | 94.49% | +13.2% |
| memory_usage_bytes_peak | 307861913.60 | 305869619.20 | -0.6% |

## Pipeline & resources

Surfaces what the HTTP-side latency table can't show: how the async write
path (flusher), the database, and Redis behave under the same workload.

### Backend container

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 27.47% | 28.80% | +4.8% |
| cpu_percent_peak | 83.44% | 94.49% | +13.2% |
| memory_usage_bytes_avg | 287873957.89 | 288589086.72 | +0.2% |
| memory_usage_bytes_peak | 307861913.60 | 305869619.20 | -0.6% |

### Flusher (async write path)

Same workload should drive similar flusher CPU. Large gaps imply the
flusher is either backlogging (buffer growing) or starved (low CPU,
high backend pressure). Memory peak proxies how deep the buffer got.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 25.60% | 25.53% | -0.3% |
| cpu_percent_peak | 45.32% | 45.05% | -0.6% |
| memory_usage_bytes_peak | 121739673.60 | 114609356.80 | -5.9% |

### Database (PostgreSQL)

Reflects how much real write work the flusher pushed to PG. Higher db CPU
with the same HTTP throughput is *good* — more rows actually committed.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 30.32% | 31.24% | +3.0% |
| cpu_percent_peak | 92.30% | 59.16% | -35.9% |

### Redis throughput

`total_commands_processed` delta is a proxy for end-to-end pipeline activity:
LPUSH from the HTTP path + LRANGE/LTRIM from the flusher + cache GETs/SETs.
Higher = more data moved through the full ingest path in the same window.

| Metric | Before | After | Δ |
|---|---|---|---|
| total_commands_processed (Δ during run) | 23774 | 25186 | +5.9% |
| cache hits | 3233 | 3502 | +8.3% |
| cache misses | 895 | 979 | +9.4% |
| cache hit_rate_pct | 78.30% | 78.20% | -0.1% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 35.26 ms | 35.31 ms | +0.1% |
| pre_benchmark.classroom_dashboard_summaries avg | 8.00 ms | 7.21 ms | -9.9% |
| pre_benchmark.student_dashboard_summaries avg | 256.00 ms | 249.69 ms | -2.5% |
| pre_benchmark.turn_insights_payload avg | 42.62 ms | 42.25 ms | -0.9% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 48.89 ms | 49.25 ms | +0.7% |
| post_benchmark.classroom_dashboard_summaries avg | 7.15 ms | 7.14 ms | -0.1% |
| post_benchmark.student_dashboard_summaries avg | 366.51 ms | 352.08 ms | -3.9% |
| post_benchmark.turn_insights_payload avg | 48.04 ms | 44.09 ms | -8.2% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
