# Benchmark Pipeline

This directory contains the benchmark tooling for the weekly-rollup and replay-archive refactor.

## Layout

- `benchmarks/k6/` - k6 workload scripts for ingest, dashboard, replay, and mixed weekly-cycle traffic
- `benchmarks/scenarios/` - JSON scenario definitions for dataset size, traffic shape, and report output
- `benchmarks/reports/` - generated reports; ignored by git except for `.gitignore`
- `benchmarks/run_scenario.py` - orchestrates dataset preparation, k6 traffic, compaction, verification, and baseline report generation

## Prerequisites

- Docker services running, especially `digitmile-backend`
- if you want k6 to follow the same exposed path as the deployed stack, keep `digitmile-nginx-proxy` running so `http://host.docker.internal` resolves to the proxy entrypoint
- Docker Compose available on the host machine
- benchmark teachers created by `prepare_benchmark_dataset` use password `benchmark_password_123`
- benchmark traffic runs inside a standalone `grafana/k6` Docker container that is attached directly to the same Docker network as `digitmile-backend`
- the default scenario path targets `http://digitmile-backend:8000` from inside that Docker network and sends `Host: localhost` so Django accepts the request without `ALLOWED_HOSTS` changes
- if you specifically want reverse-proxy benchmarking, override `base_url` and `request_host_header` in the scenario JSON

## Fast start

Prepare a small dataset without traffic:

```bash
docker exec "digitmile-backend" python manage.py prepare_benchmark_dataset \
  --teachers 1 \
  --classrooms-per-teacher 1 \
  --students-per-classroom 5 \
  --weeks 3 \
  --runs-per-student-per-week 2 \
  --avg-turns-per-run 4 \
  --card-mix-profile balanced \
  --bag-level-ratio 0.35 \
  --hot-weeks 1 \
  --clear \
  --output /tmp/manual-dataset.json
docker cp "digitmile-backend:/tmp/manual-dataset.json" "benchmarks/reports/manual-dataset.json"
```

Record a baseline analytics report:

```bash
docker exec "digitmile-backend" python manage.py benchmark_teacher_analytics <teacher_id> \
  --iterations 5 \
  --scenario-name baseline_manual \
  --output /tmp/baseline_manual.json
docker cp "digitmile-backend:/tmp/baseline_manual.json" "benchmarks/reports/baseline_manual.json"
```

Run a full scenario from the host:

```bash
python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json
```

Run one k6 script directly in Docker on the backend network:

```bash
docker run --rm \
  --network digitmile_digitmile-network \
  -v "${PWD}/benchmarks:/benchmarks" \
  -w /benchmarks \
  grafana/k6:0.49.0 run /benchmarks/k6/teacher_dashboard.js \
  -e BASE_URL=http://digitmile-backend:8000 \
  -e REQUEST_HOST_HEADER=localhost \
  -e DATASET_REPORT=/benchmarks/reports/hot_only_small_artifacts/dataset.json \
  -e SCENARIO_CONFIG=/benchmarks/scenarios/hot_only_small.json \
  -e TEACHER_USERNAME=benchmark_teacher_1 \
  -e TEACHER_PASSWORD=benchmark_password_123
```

## Scenario report contents

Each scenario report includes:

- dataset shape and compaction decisions
- pre- and post-traffic analytics benchmark summaries
- k6 summary export paths and parsed latency/error highlights
- compaction and verification outcomes when configured
- relation sizes and archive size snapshots from the backend benchmark command

## Redis policy

Redis caching is intentionally not enabled by this benchmark pipeline. Baseline reports must exist first, and Redis should only be added after those reports prove a meaningful read-latency improvement is needed.
