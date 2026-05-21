# Comparison: PgBouncer ON vs PgBouncer OFF

- **Before:** `/var/www/digitmile/benchmarks/server_reports/national_high_with_pgbouncer.json` (scenario `national_high`)
- **After:**  `/var/www/digitmile/benchmarks/server_reports/national_high.json` (scenario `national_high`)

## Headline

| Metric | Before | After | Δ |
|---|---|---|---|
| load_health | green | green | — |
| http_reqs.rate (sustained RPS) | 22.75 | 22.60 | -0.6% |
| http_req_duration.avg | 60.35 ms | 28.52 ms | -52.7% |
| http_req_duration.p(95) | 152.40 ms | 93.13 ms | -38.9% |
| http_req_duration.p(99) | — | — | — |
| dropped_iterations.count | — | — | — |
| iterations.count (completed) | 7205 | 7203 | -0.0% |

## Backend container resource usage

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 63.81% | 39.79% | -37.6% |
| cpu_percent_peak | 112.28% | 116.07% | +3.4% |
| memory_usage_bytes_peak | 392272281.60 | 395732582.40 | +0.9% |

## Pipeline & resources

Surfaces what the HTTP-side latency table can't show: how the async write
path (flusher), the database, and Redis behave under the same workload.

### Backend container

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 63.81% | 39.79% | -37.6% |
| cpu_percent_peak | 112.28% | 116.07% | +3.4% |
| memory_usage_bytes_avg | 358437476.51 | 355734968.63 | -0.8% |
| memory_usage_bytes_peak | 392272281.60 | 395732582.40 | +0.9% |

### Flusher (async write path)

Same workload should drive similar flusher CPU. Large gaps imply the
flusher is either backlogging (buffer growing) or starved (low CPU,
high backend pressure). Memory peak proxies how deep the buffer got.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 15.77% | 15.44% | -2.1% |
| cpu_percent_peak | 26.52% | 36.43% | +37.4% |
| memory_usage_bytes_peak | 84599111.68 | 84242595.84 | -0.4% |

### Database (PostgreSQL)

Reflects how much real write work the flusher pushed to PG. Higher db CPU
with the same HTTP throughput is *good* — more rows actually committed.

| Metric | Before | After | Δ |
|---|---|---|---|
| cpu_percent_avg | 28.13% | 25.90% | -7.9% |
| cpu_percent_peak | 93.79% | 107.76% | +14.9% |

### Redis throughput

`total_commands_processed` delta is a proxy for end-to-end pipeline activity:
LPUSH from the HTTP path + LRANGE/LTRIM from the flusher + cache GETs/SETs.
Higher = more data moved through the full ingest path in the same window.

| Metric | Before | After | Δ |
|---|---|---|---|
| total_commands_processed (Δ during run) | 26549 | 27363 | +3.1% |
| cache hits | 4814 | 4772 | -0.9% |
| cache misses | 2094 | 2336 | +11.6% |
| cache hit_rate_pct | 69.70% | 67.10% | -3.7% |

## Analytics latency — pre-traffic baseline (idle DB)

| Metric | Before | After | Δ |
|---|---|---|---|
| pre_benchmark.analytics_payload avg | 728.08 ms | 276.93 ms | -62.0% |
| pre_benchmark.classroom_dashboard_summaries avg | 13.94 ms | 13.31 ms | -4.5% |
| pre_benchmark.student_dashboard_summaries avg | 547.62 ms | 509.68 ms | -6.9% |
| pre_benchmark.turn_insights_payload avg | 1034.74 ms | 454.44 ms | -56.1% |

## Analytics latency — post-traffic

| Metric | Before | After | Δ |
|---|---|---|---|
| post_benchmark.analytics_payload avg | 130.96 ms | 94.35 ms | -28.0% |
| post_benchmark.classroom_dashboard_summaries avg | 18.04 ms | 12.74 ms | -29.4% |
| post_benchmark.student_dashboard_summaries avg | 579.15 ms | 492.75 ms | -14.9% |
| post_benchmark.turn_insights_payload avg | 217.37 ms | 820.16 ms | +277.3% |

## Caveats

- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;
  positive Δ on RPS / iterations = improvement.
- If either side is `red`, latency numbers are not representative — see the
  `load_health` note in each report.
- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs
  if any number looks impossibly large.
