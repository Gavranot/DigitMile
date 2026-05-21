# Comparison: Synchronous ingest (no flusher) vs Redis write buffer + flusher

- **Before:** `/var/www/digitmile/benchmarks/server_reports/before_write_buffer_ingest_isolation.json` (scenario `before_write_buffer_ingest_isolation`)
- **After:**  `/var/www/digitmile/benchmarks/server_reports/ingest_isolation.json` (scenario `ingest_isolation`)

## Toggle state

- Before overlays: `['no-flusher.yml']`, image ref: `baseline/pre-write-buffer`
- After  overlays: `none`, image ref: `tree HEAD`

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | red | green | — |
| http_reqs.rate (sustained RPS) | 19.84 | 29.70 | +49.7% |
| http_req_duration.avg | 4543.44 ms | 11.36 ms | -99.7% |
| http_req_duration.p(95) | 8147.96 ms | 26.02 ms | -99.7% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | 2237 | — | — |
| iterations.count (completed) | 4962 | 7199 | +45.1% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 47.30% | 28.80% | -39.1% |
| cpu_percent_peak | 81.93% | 94.49% | +15.3% |
| memory_usage_bytes_peak | 303143321.60 | 305869619.20 | +0.9% |

## Pipeline & resources

Surfaces what the HTTP-side latency table can't show: how the async write
path (flusher), the database, and Redis behave under the same workload.

### Backend container

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 47.30% | 28.80% | -39.1% |
| cpu_percent_peak | 81.93% | 94.49% | +15.3% |
| memory_usage_bytes_avg | 287947193.73 | 288589086.72 | +0.2% |
| memory_usage_bytes_peak | 303143321.60 | 305869619.20 | +0.9% |

### Flusher (async write path)

Same workload should drive similar flusher CPU. Large gaps imply the
flusher is either backlogging (buffer growing) or starved (low CPU,
high backend pressure). Memory peak proxies how deep the buffer got.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 0.00% | 25.53% | — |
| cpu_percent_peak | 0.00% | 45.05% | — |
| memory_usage_bytes_peak | 434176.00 | 114609356.80 | +26297.0% |

### Database (PostgreSQL)

Reflects how much real write work the flusher pushed to PG. Higher db CPU
with the same HTTP throughput is *good* — more rows actually committed.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 85.56% | 31.24% | -63.5% |
| cpu_percent_peak | 132.82% | 59.16% | -55.5% |

### Redis throughput

`total_commands_processed` delta is a proxy for end-to-end pipeline activity:
LPUSH from the HTTP path + LRANGE/LTRIM from the flusher + cache GETs/SETs.
Higher = more data moved through the full ingest path in the same window.

| Metric | Before | After | Δ |
|---|---|---|---|
| total_commands_processed (Δ during run) | 53 | 25186 | +47420.8% |
| cache hits | 0 | 3502 | — |
| cache misses | 1 | 979 | +97800.0% |
| cache hit_rate_pct | 0.00% | 78.20% | — |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 36.98 ms | 35.31 ms | -4.5% |
| pre_benchmark.classroom_dashboard_summaries avg | 16.05 ms | 7.21 ms | -55.1% |
| pre_benchmark.student_dashboard_summaries avg | 595.43 ms | 249.69 ms | -58.1% |
| pre_benchmark.turn_insights_payload avg | 46.65 ms | 42.25 ms | -9.4% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 43.34 ms | 49.25 ms | +13.6% |
| post_benchmark.classroom_dashboard_summaries avg | 18.78 ms | 7.14 ms | -62.0% |
| post_benchmark.student_dashboard_summaries avg | 1138.46 ms | 352.08 ms | -69.1% |
| post_benchmark.turn_insights_payload avg | 41.81 ms | 44.09 ms | +5.5% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
