# Management Commands

Every custom Django management command in `DigitMilePanel/digitmileapi/management/commands/`. Run inside the backend container:

```bash
docker compose exec backend python manage.py <command> [flags]
```

## Operational

### `flush_ingest_buffer`
Long-running worker that pops validated ingest payloads off the Redis list `ingest_buffer` and bulk-inserts them into Postgres. Runs continuously as the `flusher` service in `docker-compose.yml`; you should not invoke it by hand in production.

| Flag | Default | Meaning |
|------|---------|---------|
| `--batch-size` | `50` | Max items popped per iteration. |
| `--sleep-ms` | `100` | Idle sleep between flushes when the queue is empty. |

Env alternatives: `INGEST_BUFFER_BATCH_SIZE`, `INGEST_BUFFER_SLEEP_MS`. See `docs/decisions/write-buffering-adr.md`.

### `compact_weekly_runs [YYYY-MM-DD]`
Aggregates raw `Run` / `TurnEvent` / `SpecialTileTrigger` rows for a given week into the `StudentWeek*` rollup tables, writes replay archives to disk, verifies them, and deletes the raw rows. Invalidates the `teacher_stats_viz:*` dashboard cache. Runbook: `docs/guides/rollup-runbook.md`.

| Flag | Meaning |
|------|---------|
| `--week-start YYYY-MM-DD` | Pin to a specific Monday week start. Without it, processes all pending weeks. |
| `--clear-game-map` | Also nulls `Run.game_map` for archived weeks (significant space saving). |

### `verify_weekly_rollups [YYYY-MM-DD]`
Recomputes each rollup from the raw rows (or archive) for a sample of students/runs and compares against what's stored. Useful after a migration or suspected data corruption.

| Flag | Meaning |
|------|---------|
| `--week-start YYYY-MM-DD` | Pin to a week. |
| `--require-archives` | Fail if any run lacks a replay archive. |
| `--verify-run-buckets` | Also recompute and compare `StudentRunBucketTrend`. |
| `--sample <N>` | Sample size for student-level checks. |
| `--sample-runs <N>` | Sample size for run-level checks. |

### `rebuild_weekly_rollups [YYYY-MM-DD]`
Drops and recomputes all `StudentWeek*` rows for a week from scratch. Use after a bugfix in the aggregation code or to recover from divergence.

| Flag | Meaning |
|------|---------|
| `--week-start YYYY-MM-DD` | Week to rebuild. |
| `--update-compaction` | Also updates the `WeeklyCompactionRun` row for that week. |
| `--rebuild-run-buckets` | Also rebuilds `StudentRunBucketTrend`. |

### `archive_week_replays [--week-start YYYY-MM-DD]`
Writes replay archives for any `Run` in the given week that doesn't have one yet. Normally invoked by `compact_weekly_runs`; use standalone for recovery.

### `verify_replay_archives [--week-start YYYY-MM-DD]`
Recomputes the SHA-256 of each `ReplayArchive` file on disk and compares with the stored checksum. Marks mismatches `CORRUPT` or `MISSING`.

### `clear_school_data --school-id sch_...`
Cascades a delete of everything tied to a school: teachers, classrooms, students, runs, turns, triggers, rollups. Irreversible. The prefix is validated — there is no wildcard.

### `create_superuser`
Runs automatically inside the backend container's boot command. Reads `DJANGO_SUPERUSER_{USERNAME,PASSWORD,EMAIL}` from env and creates the superuser if it doesn't already exist. If any env var is unset, logs a warning and skips.

### `setup_teachers_group`
Creates the Django auth `Teachers` group and grants the model-level permissions used by the `IsTeacher` DRF permission. Also runs automatically via `apps.py`'s `post_migrate` hook; manual invocation is mostly for recovery.

## Seeding / benchmark data

### `seed_database`
Generates schools → teachers → classrooms → students → runs → turns → triggers, then aggregates weekly rollups and optionally compacts old weeks. Use this to get a populated local stack.

| Flag | Default | Meaning |
|------|---------|---------|
| `--preset {low,medium,high}` | — | Convenience profile; sets sensible defaults for the other flags. |
| `--weeks <N>` | preset-driven | Total weeks of history. |
| `--hot-weeks <N>` | | How many of `--weeks` stay as raw data (not compacted). |
| `--runs-per-student-per-week <N>` | | |
| `--clear` | off | Delete existing data first. |
| `--compact-weeks` | off | Compact every non-hot week after seeding. |
| `--anchor-week-start YYYY-MM-DD` | today | Pin the schedule to a specific Monday — required for reproducible benchmark runs. |

### `prepare_benchmark_dataset`
Like `seed_database` but tuned for k6 benchmarks: emits a `dataset.json` report with synthetic-clock metadata that the k6 scripts read, and accepts fine-grained traffic-shape flags.

| Flag | Meaning |
|------|---------|
| `--teachers`, `--classrooms-per-teacher`, `--students-per-classroom` | Topology. |
| `--weeks`, `--runs-per-student-per-week`, `--avg-turns-per-run` | Volume. |
| `--card-mix-profile`, `--bag-level-ratio` | Shape of the card mix. |
| `--hot-weeks`, `--compact-weeks` | Same semantics as `seed_database`. |
| `--anchor-week-start YYYY-MM-DD` | Synthetic Monday — drives the recording window logic during the benchmark. |
| `--output <path>` | Where to write the dataset report (default: `benchmarks/reports/...`). |
| `--clear` | Wipe existing data first. |

### `benchmark_teacher_analytics`
Times the execution of the analytics helper functions against a seeded dataset. Useful to spot regressions in `rollup_analytics.py`.

| Flag | Meaning |
|------|---------|
| `--teachers <N>` | How many teachers to sample. |
| `--students-per-teacher <N>` | |
| `--weeks <N>` | Analytics window. |
| `--skip-rollups` | Run only the read-path helpers; skip regenerating rollups. |
