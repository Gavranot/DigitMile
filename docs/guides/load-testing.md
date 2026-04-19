# Load Testing

The load-testing framework lives co-located with the code that drives it at `benchmarks/`. That README is the source of truth for running scenarios; the pointers below are for navigating the pieces.

## Entry point

```bash
python benchmarks/run_scenario.py benchmarks/scenarios/<name>.json
```

`run_scenario.py` spins up an isolated compose stack (`benchmarks/docker-compose.benchmark.yml`), seeds a synthetic-clock dataset via `prepare_benchmark_dataset`, runs the specified k6 script(s) against the benchmark backend, samples Docker stats, and writes a JSON report under `benchmarks/reports/`.

Required env vars on the host running `run_scenario.py`:

- `BENCHMARK_BACKEND_IMAGE` — Docker image the benchmark stack should use (e.g. `dockerhubuser/digitmile-backend:prod-latest`, or the local alias `digitmile-backend:latest` on a CI runner).
- `BENCHMARK_TIME_OVERRIDE_ENABLED` — the benchmark stack's backend sets this `True` automatically via its compose config; in production the variable stays `False`.

## Scenarios

All scenarios live in `benchmarks/scenarios/`:

| Scenario | Intent |
|----------|--------|
| `hot_only_small.json` | Smoke — minimal hot-week traffic. |
| `bag_conditional_compaction_smoke.json` | Smoke — exercises bag-conditional analytics compaction. |
| `realistic_school_day.json` | Moderate mixed workload. |
| `ingest_isolation.json` | Ingest-only ramp to find write throughput ceiling. |
| `mixed_semester_medium.json`, `mixed_semester_heavy.json` | Mixed read+write across a longer synthetic timeline. |
| `hot_week_read_write_heavy.json` | Heavy concurrent read+write on the current hot week. |
| `hot_week_read_write_heavy_traffic_only.json` | Same traffic shape, but no dataset regeneration — faster iteration. |
| `compaction_under_read_load.json` | Dashboard reads while weekly compaction runs in background. |
| `national_medium.json`, `national_high.json` | National-scale load model (see `docs/research/north-macedonia-weekly-load-estimate.md`). |
| `retry_storm_ingest.json` | Ingest spike with high retry rate. |
| `stress_ramp.json` | Pure stress ramp until failure. |

## k6 scripts

`benchmarks/k6/`:

| Script | Purpose |
|--------|---------|
| `common.js` | Shared helpers — CSRF, synthetic-time headers, payload builders. |
| `ingest.js` | `POST /panel/api/runs/ingest/` writer with constant-arrival-rate executor. |
| `teacher_dashboard.js` | Teacher dashboard + viz-data reader. |
| `mixed_weekly_cycle.js` | Concurrent ingest + teacher + replay traffic classes. |
| `replay.js` | Replay archive fetch + playback. |

## Design context

- **Synthetic benchmark clock.** Ingest respects a `X-Benchmark-Reference-Time` header only when `BENCHMARK_TIME_OVERRIDE_ENABLED=True`. Payload timestamps come from the dataset report, not `Date.now()`. See `docs/decisions/hot-week-load-testing-plan.md` + `docs/decisions/hot-week-load-testing-checklist.md`.
- **Capacity findings.** Current hardware caps at ~16 req/s ingest on 2 vCPU. Full analysis in `docs/decisions/hardware-sizing.md`; pending code/schema optimizations that should close the gap to ~22–25 req/s in `docs/decisions/ingest-optimization-plan.md`.
- **Why benchmark backend+db directly.** The primary benchmark lane bypasses the reverse proxy to isolate application/DB bottlenecks from proxy or static-file noise.

## Interpreting a report

Reports are JSON under `benchmarks/reports/<timestamp>_<scenario>/`. The `summary.json` at the top level has the headline numbers; the sibling `artifacts/` directory has the raw k6 output, the dataset report, and Docker-stats samples.

Be careful with `http_req_failed` — it counts the `409` closed-week rejections as failures. Scenarios that intentionally test closed-week behavior must be read via the per-check counters in the k6 summary, not the overall failure rate.
