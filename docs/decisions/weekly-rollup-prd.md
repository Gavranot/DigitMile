# Weekly Analytics Rollup and Replay Archive Refactor PRD

Last updated: 2026-03-10

## Why this refactor exists

The backend currently uses `Run`, `TurnEvent`, and `SpecialTileTrigger` as the source of truth for both teacher analytics and replay. That coupling creates two problems at production scale:

- raw turn-level storage grows too quickly,
- historical analytics get more expensive as more raw gameplay accumulates.

This refactor separates those concerns:

- analytics move to weekly aggregate rollups,
- indefinite replay moves to compressed per-run archive files stored on disk.

## Problem statement

Today, historical teacher analytics are built by scanning raw gameplay history from:

- `Run`
- `TurnEvent`
- `SpecialTileTrigger`

Several analytics helpers parse card payloads repeatedly, replay turn order, and reconstruct gameplay state at request time. The dashboard also computes student summaries in Python from many runs. As the semester grows, historical queries become slower and the hot relational dataset becomes larger.

At the same time, replay must remain available indefinitely, which means raw gameplay information cannot simply disappear unless it is moved somewhere else.

## Product goals

- Keep replay available indefinitely for every run.
- Limit hot-database retention of raw `TurnEvent` and `SpecialTileTrigger` rows to a short rolling window.
- Serve historical analytics from weekly rollup tables instead of raw turn history.
- Preserve as many current teacher metrics as possible exactly.
- Redesign only the metrics that depend on long raw per-run sequences.
- Keep write-time and weekly maintenance CPU predictable.
- Add a benchmark process that proves the refactor improved the system.

## Implementation progress

The following foundation work is now implemented in the codebase:

- weekly rollup schema tables and migration support,
- replay archive metadata and on-disk archive helpers,
- archive storage settings and Docker volume wiring,
- archive verification and weekly archive management commands,
- a first weekly aggregation writer that fills the rollup tables from raw weekly gameplay,
- a first weekly compaction command that aggregates, archives, verifies, and deletes hot turn-level rows,
- initial replay cutover so compacted runs can still be replayed from archive,
- initial dashboard and visualization cutover for historical level summaries and turn-insight aggregate charts,
- rebuild, verification, and benchmark management commands,
- foundational automated tests for archive, aggregation, compaction, and rollup-backed analytics flows.

The following next-phase items are now additionally implemented:

- `/panel/api/runs/ingest/` accepts full Unity payload semantics in addition to the canonical snake_case contract,
- `/panel/api/runs/ingest/` now preserves `place`, `game_map`, Unity-equivalent elapsed-time clamping, and replay-critical turn metadata with idempotent retry behavior,
- closed-week ingest policy enforcement now rejects late statistical writes cleanly with explicit structured logging,
- weekly card-type decision-time rollups now preserve clipped and raw timing aggregates for long-horizon historical charts,
- student learning-curve reads now use deterministic 5-run trend buckets plus hot-run tail merging instead of weekly-only history,
- compaction, rebuild, and verification flows now rebuild historical run buckets and reconcile archives plus extended rollup totals before raw deletion,
- benchmark dataset preparation, Dockerized k6 traffic generation, scenario orchestration, and baseline analytics reporting are now available,
- operator documentation now covers ingest, compaction, verification, rebuild, benchmarking, and manual phase validation.

The following items still need additional implementation depth:

- stronger reconciliation and rebuild tooling for large-scale operational recovery,
- optional Redis caching only if future benchmark evidence justifies the added operational complexity.

## Non-goals

- Introduce external object storage.
- Preserve every chart in its exact current implementation if a weekly equivalent is more efficient and still meaningful.
- Replace replay with screenshots or summaries.
- Depend on request-time multithreading as the primary scaling strategy.

## Guiding principles

- Store mergeable sufficient statistics, not only final percentages.
- Keep `Run` as the durable canonical session index in PostgreSQL.
- Treat replay storage and analytics storage as separate systems.
- Compact only closed historical weeks.
- Make compaction idempotent, verifiable, and restartable.
- Prefer SQL aggregation and bulk operations over Python loops during historical processing.
- Keep the archive format simple enough to inspect and recover manually.

## Target architecture

### Hot relational data

Keep in PostgreSQL:

- all `Run` rows permanently,
- recent `TurnEvent` rows inside the active retention window,
- recent `SpecialTileTrigger` rows inside the active retention window,
- weekly rollup tables permanently,
- replay archive metadata permanently.

### Cold replay storage

Store one compressed replay artifact per run on disk:

- file format: `run_<id>.json.gz`
- storage location: mounted persistent volume, not container-local ephemeral storage

These files become the source of truth for replay of compacted historical runs.

### Read model split

- current hot window:
  - replay may read relational tables,
  - analytics may temporarily read raw tables during the transition period
- closed historical weeks:
  - analytics read weekly rollups,
  - replay reads archive files from disk

## Why weekly rollups work mathematically

Weekly rows must store the ingredients needed to recompute final metrics later.

Examples:

- win rate needs `wins` and `runs`
- accuracy needs `correct_moves` and `wrong_moves`
- average score needs `score_sum` and `score_count`
- standard deviation needs `value_sum`, `value_count`, and `value_sum_sq`

Semester analytics are then built by summing week rows over the target range and recomputing final formulas from the combined totals.

### Example

If one student has:

- week 1: `wins = 8`, `runs = 10`
- week 2: `wins = 15`, `runs = 20`

then semester totals are:

- `wins = 23`
- `runs = 30`
- `win_rate = 23 / 30`

The same method applies to accuracy, score, elapsed time, tile hotspots, card-family counts, special-tile counts, number-choice distributions, and conditional-card statistics.

## Historical metrics strategy

### Metrics that should remain exact

These should remain exact if the weekly rollups store the right numerators, denominators, sums, and grouped counts:

- total runs
- wins
- win rate
- correct move totals
- wrong move totals
- overall accuracy
- average score
- score min and max
- average elapsed time
- elapsed min and max
- score and elapsed standard deviation
- win rate by level
- score by level
- wrong and correct totals by level
- mistake hotspots by level and tile
- special tile counts by level and type
- special-tile chain-length distributions
- card-family accuracy
- card-family exposure and choice counts
- decision-time averages by card family and level
- tile-conditional counts and else rates
- bag-conditional counts and else rates
- back-card usage by place
- foreach-context usage
- number-choice distributions
- number-decision-time averages

### Metrics that should be redesigned as weekly trend metrics

These should continue to exist, but should be computed from weekly points rather than a semester-long raw per-run sequence:

- improvement rate
- learning-curve slope
- learning-curve trend
- attention and reward heuristics
- recency-weighted score over the semester

The new definition should use one point per week, optionally weighted by run count or move count.

### Metrics that cannot remain exact without extra distribution storage

These need redesign, approximation, or hot-window-only behavior:

- exact per-run scatterplots across the entire semester
- exact raw per-run sequences for all historical runs
- exact medians and quartiles unless histograms or sketches are stored
- exact long-horizon per-game learning trajectories

## Replay archive design

### Canonical archive format

Each replay archive should contain the full payload needed to reconstruct the current replay view:

- schema version
- run metadata
- student and classroom identifiers needed for lookup
- `game_map`
- ordered turns
- grouped special triggers
- archive timestamp
- checksum metadata

Recommended encoding:

- UTF-8 JSON
- gzip compression
- filename `run_<id>.json.gz`

### Disk layout

Recommended path layout:

- `replay-archives/YYYY/MM/run_<id>.json.gz`

This keeps directories manageable and allows easier auditing.

### Write rules

- build canonical replay payload
- serialize JSON
- write compressed bytes to a temporary file
- atomically rename into final location
- compute checksum
- persist archive metadata only after the file is verified

### Replay read rules

- if raw turn rows still exist, replay can read from PostgreSQL
- if raw turn rows were compacted, replay loads the archive file and returns the same logical payload shape to the template

### Teacher export flow

Teachers should be able to request a class-week replay export.

The system should:

- select archived runs for the class and week,
- bundle the relevant `run_<id>.json.gz` files into one downloadable zip,
- include a manifest file with run ids, student ids, student names, classroom, week range, and checksums.

This zip is an export convenience, not the canonical archive format.

## Weekly compaction workflow

### Step 1: select a closed week

Compaction runs only on weeks outside the hot retention window.

The compaction policy should define:

- week boundary logic,
- grace period for late-arriving runs,
- whether compaction is based on `Run.created_at` or another canonical ingestion timestamp.

### Step 2: identify all source rows for the target week

Collect:

- all `Run` rows in the week,
- all related `TurnEvent` rows,
- all related `SpecialTileTrigger` rows.

### Step 3: compute weekly rollups

Aggregate source rows into rollup tables using idempotent upserts.

The rollups must store mergeable sufficient statistics rather than final percentages only.

### Step 4: archive replay payloads

For every run in the target week:

- build replay payload,
- compress and write archive file,
- compute checksum,
- record archive metadata.

### Step 5: verify completeness

Before deletion, verify:

- all expected archives exist,
- checksums pass,
- rollup writes succeeded,
- sampled replay reads from archive succeed,
- row counts reconcile with the source data.

### Step 6: compact hot raw rows

Only after successful verification:

- delete historical `SpecialTileTrigger` rows,
- delete historical `TurnEvent` rows,
- optionally clear `Run.game_map` if the archive is now the canonical replay source.

`Run` rows are retained.

### Step 7: record compaction state

Persist:

- status,
- timestamps,
- counts of rows archived and compacted,
- bytes written,
- compression ratio,
- failures or warnings.

## Application changes required

### Models

Add:

- replay archive metadata model or fields,
- weekly rollup tables,
- weekly compaction state table.

### Management commands

Add commands for:

- weekly compaction,
- archive verification,
- rollup rebuild for a target week,
- benchmark/report support if desired.

### Replay view

Refactor replay loading so older runs can be served from archive files with the same teacher authorization rules that already exist for relational replay.

### Dashboard and viz endpoints

Refactor historical reads to use rollups.

The long-term target is:

- hot-window analytics from raw tables when needed,
- historical analytics from weekly rollups,
- identical or intentionally redesigned payload shapes for the frontend.

### Deployment configuration

Add a persistent archive volume to runtime configuration, especially production compose, so replay files survive deploys and container replacement.

## Detailed implementation sequence

### 1. Add archive storage configuration

- add archive root setting
- mount a durable archive volume in local and production runtime configs
- document filesystem ownership and backup expectations

### 2. Add schema and migrations

- add replay archive metadata model or fields
- add weekly rollup tables
- add weekly compaction state table
- add indexes and uniqueness constraints by rollup grain

### 3. Implement archive serializer and reader

- define canonical archive JSON schema
- implement replay archive builder from `Run`, `TurnEvent`, and `SpecialTileTrigger`
- implement gzip writer
- implement checksum generation and verification
- implement archive reader that returns the same replay payload shape the template expects

### 4. Implement weekly rollup engine

- aggregate raw run-level metrics
- aggregate level metrics
- aggregate card-family metrics
- aggregate conditional metrics
- aggregate hotspot metrics
- aggregate special-tile metrics
- aggregate number-choice metrics
- persist all results via upsert semantics

### 5. Implement weekly compaction command

- select target week
- build rollups
- archive all runs
- verify results
- compact old rows
- record lifecycle status
- make reruns safe

### 6. Add archive-backed replay support

- keep current hot replay behavior
- add cold replay loading from archive path
- preserve permission checks for teachers and superusers

### 7. Refactor historical analytics reads

- migrate dashboard history queries to rollups
- migrate chart endpoints to rollups for closed weeks
- keep a fallback raw path for current week where necessary

### 8. Redesign trend metrics

- redefine learning-curve style metrics over weekly points
- document the new formulas in code and docs
- adjust labels in the UI if they no longer reflect per-run history

### 9. Add class-week replay export

- select archive files by class and week
- generate downloadable zip plus manifest
- enforce teacher access scope

### 10. Add full validation, benchmarking, and operational tooling

- automated tests
- archive integrity checks
- reconciliation reports
- baseline vs post-refactor benchmark runbook

## Testing strategy

### Unit tests

Add unit tests for:

- week boundary calculation
- sufficient-statistics math
- merge formulas across multiple weeks
- trend calculations over weekly points
- archive path generation
- checksum generation and verification
- compaction state transitions
- idempotent rollup upserts

### Integration tests

Add end-to-end tests that:

- ingest runs through the current API contract,
- run weekly compaction,
- verify rollup totals against source rows,
- verify hot replay still works,
- verify archived replay works after compaction,
- verify raw turn rows are gone after compaction,
- verify dashboard endpoints still return valid data.

### Replay archive tests

Add tests for:

- archive creation,
- archive readback,
- missing file behavior,
- checksum mismatch behavior,
- week export zip generation,
- manifest correctness.

### Authorization tests

Ensure replay permissions still hold after archive-backed replay is introduced:

- teacher can access their own student archives,
- teacher cannot access another teacher's archives,
- superuser can access any archive.

### Rebuild and rerun tests

Test:

- rerunning compaction does not double-count,
- rebuilding rollups for a week is safe,
- archive verification detects drift,
- compaction only deletes rows from verified completed weeks.

## Benchmark strategy

The benchmark process must compare baseline and refactored code on the same seeded dataset.

### Dataset generation

Use the existing `seed_database` command to generate realistic runs, turns, triggers, maps, card types, and number-choice behavior.

Important rule:

- seed once,
- snapshot the database,
- reuse the exact same dataset for pre-refactor and post-refactor runs.

### Workloads to measure

#### Ingestion

Measure:

- `insertRunData`
- `runs/ingest`

Capture:

- median latency
- p95 latency
- backend CPU
- DB CPU
- query count
- memory impact

#### Dashboard load

Measure `/panel/teacher/statistics/` for:

- no filters
- grade filter
- classroom filter

Capture:

- median and p95 latency
- query count
- backend CPU
- backend memory

#### Visualization load

Measure `/panel/teacher/statistics/viz-data/` for:

- `section=analytics`
- `section=turn_insights`
- uncached run
- warm-cache run

Capture:

- median and p95 latency
- query count
- CPU
- payload size

#### Replay load

Measure:

- hot recent run replay
- archived historical run replay

Capture:

- latency
- CPU
- memory
- payload assembly cost

#### Compaction workload

Measure:

- full week compaction
- rerun of the same week for idempotency
- archive verification pass

Capture:

- total runtime
- CPU
- memory
- rows aggregated
- rows compacted
- archive bytes written
- compression ratio

### Storage measurements

Record before and after:

- total database size
- size of `Run`
- size of `TurnEvent`
- size of `SpecialTileTrigger`
- size of rollup tables
- total archive size on disk
- average archive size per run
- compression ratio: raw replay payload size divided by compressed archive size

### Relative success targets

The refactor is successful when all of the following are true:

- historical dashboard requests are materially faster than the baseline
- historical chart requests are materially faster than the baseline
- historical analytics request cost no longer scales with total raw turn history volume in the same way as before
- ingestion remains within an acceptable regression band
- archived replay remains practical for teacher use
- hot-table growth is capped by the chosen retention window
- archive plus rollup storage for old weeks is lower than keeping all old raw turn data hot in PostgreSQL

## Functional success metrics

- teachers can replay both hot and archived runs
- archived replay is transparent to the teacher
- class-week replay download works
- historical analytics can be computed across arbitrary semester ranges from weekly rollups
- compaction can be rerun safely
- integrity checks can detect missing or corrupt archives

## Data correctness success metrics

- rollup totals reconcile with raw source totals for sampled weeks
- semester totals built from weekly rollups match baseline raw-history results for metrics intended to remain exact
- redesigned weekly trend metrics are internally consistent and stable
- no duplicate counting occurs on compaction reruns

## Operational success metrics

- compaction can be monitored
- archive verification can be run on demand
- persistent archive storage survives deploys
- failures leave enough state to recover safely without hidden partial deletion

## Expected repository touch points

Likely files and directories impacted:

- `DigitMilePanel/digitmileapi/models.py`
- `DigitMilePanel/digitmileapi/views.py`
- `DigitMilePanel/digitmileapi/analytics.py`
- `DigitMilePanel/digitmileapi/serializers.py`
- `DigitMilePanel/digitmile/urls.py`
- `DigitMilePanel/digitmile/settings.py`
- `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`
- `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_run_replay.html`
- `DigitMilePanel/digitmileapi/management/commands/`
- `DigitMilePanel/digitmileapi/tests.py` or a new test package
- `docker-compose.yml`
- `docker-compose.prod.yml`

## Final outcome

When complete, the system should:

- preserve indefinite replay,
- move old replay state out of hot PostgreSQL into compressed per-run archive files,
- keep `Run` as the permanent session index,
- use weekly rollups as the historical analytics source,
- preserve most existing teacher metrics exactly,
- redefine only the metrics that fundamentally depend on long raw run sequences,
- give the team a clear benchmark method to validate that the refactor improved both performance and storage behavior.
