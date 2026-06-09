# Running the Tests

DigitMile has two backend test modules:

- `DigitMilePanel/digitmileapi/tests.py` — API + ingest + registration + rollup compaction behavior.
- `DigitMilePanel/digitmileapi/test_rollup_accuracy.py` — property-style checks that `StudentWeek*` rollup values recomputed from raw rows match what the aggregation code wrote.

There is no `pytest.ini`; the stock Django test runner is used (`manage.py test`). CI does **not** currently execute the test suite — see `docs/guides/ci-cd.md`.

## Run everything

```bash
docker compose exec backend python manage.py test digitmileapi
```

The first run creates a throw-away test database against whatever `DATABASES['default']` points at. Subsequent runs are faster if you pass `--keepdb`.

## Target a single test

```bash
docker compose exec backend python manage.py test digitmileapi.tests.RunIngestionFlowTests
docker compose exec backend python manage.py test digitmileapi.tests.RunIngestionFlowTests.test_closed_week_rejection
```

Same format works for `test_rollup_accuracy`.

## What each file covers

### `tests.py`
- Ingest path via both the Unity-shaped payload and the canonical snake_case payload.
- Idempotent retries return `200` without duplicating `Run` rows.
- Closed-week rejection returns `409` with the `week_start` / `recording_closed_at` payload.
- `BENCHMARK_TIME_OVERRIDE_ENABLED` toggle behavior: header honored only when set.
- Weekly compaction: `compact_weekly_runs` correctly transitions `WeeklyCompactionRun.status`, writes `ReplayArchive` rows, and deletes raw rows only after verification.
- `StudentRunBucketTrend` rebuild math.
- Registration form validation and approval/rejection state transitions.

### `test_rollup_accuracy.py`
Seeds a small known-good dataset, runs the aggregation, then recomputes the rollup values by hand and asserts equality within floating-point tolerance. The intent is to catch regressions in `weekly_aggregation.py` where a summed metric drifts silently.

## Fast feedback while editing a single test

```bash
docker compose exec backend python manage.py test digitmileapi.tests.X --keepdb --verbosity=2 --failfast
```

`--keepdb` reuses the last test DB (migrations only re-run on schema change).

## Testing against live-shaped data

Tests use `APIClient` against in-process Django; they do not go through the Gunicorn/Nginx pipeline. If you need an integration-style test against a running stack, use the benchmark tooling instead:

```bash
python benchmarks/run_scenario.py benchmarks/scenarios/hot_only_small.json
```

See `docs/guides/load-testing.md`.

## Adding a new test

- Put model / ingest / compaction logic tests in `tests.py` alongside the existing `TestCase` classes.
- Put "rollup value equals handroll" tests in `test_rollup_accuracy.py`.
- Do not mock the database — DigitMile tests run against Postgres. The compaction/rollup code is SQL-heavy and mocked tests will silently disagree with reality.
