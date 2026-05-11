# Ingest Performance Optimizations

> **Status: SUPERSEDED (2026-05-11).** Optimizations 1 and 2 targeted `RunIngestionSerializer` / `UnityRunUploadPayloadSerializer` in `serializers.py`, both removed on 2026-05-11 when the Unity client migrated from `insertRunData/` to `runs/ingest/`. The new pydantic-based path in `ingest_router.py` doesn't have the double-validation or double-student-check problem these optimizations addressed. Optimizations 3–5 (schema migrations on `TurnEvent`/`Run` JSONB columns) may still be relevant — re-evaluate against current `models.py` before acting. Original status note preserved below for context.

> **Original status (2026-03-18): NOT YET APPLIED.** The five optimizations below are a plan, not an implemented change. Verified against `models.py` on 2026-04-19: `offered_cards`, `bot_positions_before`, `bot_positions_after`, `chosen_card`, and `game_map` all still exist on their respective models. The Redis write-buffering described in `write-buffering-adr.md` is a separate, already-shipped optimization; it is not one of the five below.

Last updated: 2026-03-18

## Context

Benchmarking on the production server (2 vCPU, 3.824 GiB, PostgreSQL 16, 5 Gunicorn workers, PgBouncer transaction pooling) shows the ingest endpoint saturating backend CPU at ~114% avg during national-medium load (35 RPS target). The server sustains ~16.5 RPS before dropping requests. The DB is at ~49% CPU and has headroom; the constraint is Python-side processing per request.

Two categories of work are identified:
- **Code-only changes** (no schema migration): fix redundant work in the serializer pipeline
- **Schema migrations**: remove JSONB columns from `TurnEvent` and `Run` that are only used for replay, reducing per-row I/O cost for analytics queries

Each optimization is numbered. Implement and benchmark them in order. Do not combine multiple into one deploy — isolate each so the benchmark result is attributable to that specific change.

---

## Optimization 1 — Eliminate double student existence check

**Type:** Code only. No migration. Low risk.

### Problem

Every ingest request from Unity causes two identical `Student.objects.filter(pk=...).exists()` DB queries:

1. `UnityRunUploadPayloadSerializer.validate_userID()` — line ~598 in `serializers.py`
2. `CanonicalRunIngestionPayloadSerializer.validate_student_id()` — line ~240 in `serializers.py`

`RunIngestionSerializer.to_internal_value()` calls both serializers sequentially for Unity payloads. The student ID is the same value both times. The second check is a pure waste of a DB round-trip.

### Fix

In `RunIngestionSerializer.to_internal_value()`, after validating the Unity payload with `UnityRunUploadPayloadSerializer`, pass a flag or override to `CanonicalRunIngestionPayloadSerializer` to skip the student existence check when the student was already verified in the Unity pass.

The simplest approach: add a `skip_student_check` context flag to `CanonicalRunIngestionPayloadSerializer` and check it in `validate_student_id`.

**Files to change:**
- `DigitMilePanel/digitmileapi/serializers.py`

### Expected benefit

One fewer DB query per ingest request. At 16.5 RPS that is 16.5 queries/sec saved — small in absolute terms, but every query requires a PgBouncer checkout and a PostgreSQL round-trip.

### How to test

Run `ingest_isolation` benchmark before and after. Compare `http_req_duration` avg and p95. Also verify the endpoint still rejects unknown student IDs correctly.

---

## Optimization 2 — Skip canonical re-validation for Unity path

**Type:** Code only. No migration. Medium risk.

### Problem

`RunIngestionSerializer.to_internal_value()` for Unity payloads:

1. Validates the full payload with `UnityRunUploadPayloadSerializer` — constructs and validates ~6 nested serializer objects per turn (UnityTurnEventSerializer, UnityTileSnapshotSerializer × 2, UnityPlayerPositionSnapshotSerializer × 2, UnityBotPositionSnapshotSerializer × N, UnitySpecialTileTriggerSerializer × M)
2. Calls `normalize_unity_run_ingestion_payload()` — loops through all turns in Python to rename fields
3. Then validates the normalized payload again with `CanonicalRunIngestionPayloadSerializer` — constructs and validates `TurnEventInputSerializer` + `SpecialTileTriggerInputSerializer` for every turn a second time

For a 6-turn run this means 12 turn serializer instances where 6 are sufficient. This is pure Python object allocation and field-level validation CPU with no correctness benefit: `normalize_unity_run_ingestion_payload` is deterministic and the canonical serializer cannot catch anything the Unity serializer did not already catch.

### Fix

In `RunIngestionSerializer.to_internal_value()`, when the Unity path is taken, return the normalized data directly without passing it through `CanonicalRunIngestionPayloadSerializer`. The canonical serializer is only needed for the non-Unity path (direct API callers sending snake_case payloads).

```python
def to_internal_value(self, data):
    if _looks_like_unity_run_payload(data):
        unity_serializer = UnityRunUploadPayloadSerializer(data=data)
        unity_serializer.is_valid(raise_exception=True)
        return normalize_unity_run_ingestion_payload(unity_serializer.validated_data)

    # Non-Unity (canonical) path only
    canonical_serializer = CanonicalRunIngestionPayloadSerializer(data=data)
    canonical_serializer.is_valid(raise_exception=True)
    return canonical_serializer.validated_data
```

**Files to change:**
- `DigitMilePanel/digitmileapi/serializers.py`

### Risk

The canonical serializer performs cross-field validation (`correct_moves` vs turn count, `player_won` vs `place`, `elapsed_ms` derivation). These checks are also present in `UnityRunUploadPayloadSerializer.validate()`. Verify before removing the canonical pass that every cross-field check in `CanonicalRunIngestionPayloadSerializer.validate()` is either:
- Already covered by `UnityRunUploadPayloadSerializer.validate()`, or
- Covered by `normalize_unity_run_ingestion_payload()` logic

If any check is unique to the canonical serializer, move it into the Unity serializer's `validate()` before removing the double-pass.

### Expected benefit

Eliminates ~half the Python serializer CPU per Unity ingest request. This is the most direct lever on backend CPU at the current bottleneck.

### How to test

Run `ingest_isolation` benchmark before and after. Compare throughput (req/sec) and backend CPU avg. Also send a deliberately malformed payload (wrong `correct_moves`, mismatched `player_won`/`place`) and confirm it is still rejected with a 400.

---

## Optimization 3 — Remove `offered_cards`, `bot_positions_before`, `bot_positions_after` from TurnEvent

**Type:** Schema migration. High impact on analytics. Requires replay archive pre-check.

### Problem

`TurnEvent` stores three large JSONB columns that are not used by any analytics query:

| Column | Content | Size estimate per turn |
|---|---|---|
| `offered_cards` | List of 3–4 card objects, each ~200 bytes JSON | ~600–800 bytes |
| `bot_positions_before` | List of 3 `{tileMapIndex, botID}` objects | ~150 bytes |
| `bot_positions_after` | List of 3 `{tileMapIndex, botID}` objects | ~150 bytes |

These fields are stored for replay. The replay archive system (`ReplayArchive` model, `replay_archives.py`) already archives complete run data to compressed files on disk before compaction. After compaction, analytics queries scan only hot-week `TurnEvent` rows. Those rows still carry this JSONB even though it is never read by analytics.

With 36,000 hot-week turn events in the national-medium dataset, these three columns represent ~32–40 MB of JSONB being read off disk and transferred per analytics query that touches `TurnEvent` at all, even though none of it is used.

Removing them reduces per-row size by ~50–60%, which directly reduces I/O for every analytics and dashboard query.

### Prerequisite: verify replay archives are complete

**Before running this migration**, confirm that all compacted weeks have valid, readable replay archives. Run:

```bash
docker exec -e DB_HOST=db digitmile-backend python manage.py shell
```

```python
from digitmileapi.models import WeeklyCompactionRun, ReplayArchive
from django.db.models import Count

# All compacted weeks
compacted = WeeklyCompactionRun.objects.filter(status='COMPACTED')
print(f"Compacted weeks: {compacted.count()}")

# Check archives for those weeks
for week in compacted:
    archives = ReplayArchive.objects.filter(
        run__created_at__date__gte=week.week_start,
        run__created_at__date__lte=week.week_end,
    )
    broken = archives.exclude(archive_status='READY')
    if broken.exists():
        print(f"BROKEN: week {week.week_start} has {broken.count()} non-READY archives")
    else:
        print(f"OK: week {week.week_start} ({archives.count()} archives)")
```

Do not proceed with this migration until all compacted weeks show OK.

### Fix

1. Create a Django migration that removes the three columns from `TurnEvent`
2. Remove the fields from `TurnEvent` in `models.py`
3. Remove the fields from `TurnEventInputSerializer` in `serializers.py`
4. Remove the fields from `TurnEventSerializer` (output) in `serializers.py`
5. Remove the fields from the Unity normalizer in `run_ingestion.py` (`normalize_unity_run_ingestion_payload`) and from `UnityTurnEventSerializer`
6. Remove the fields from the ingest view (`views.py`) where `TurnEvent` objects are constructed
7. Verify nothing in `analytics.py`, `weekly_aggregation.py`, `rollup_analytics.py`, or any template reads these fields

**Files to change:**
- `DigitMilePanel/digitmileapi/models.py`
- `DigitMilePanel/digitmileapi/serializers.py`
- `DigitMilePanel/digitmileapi/run_ingestion.py`
- `DigitMilePanel/digitmileapi/views.py`
- New migration file in `DigitMilePanel/digitmileapi/migrations/`

### Expected benefit

- Ingest: ~30–40% less data written to PostgreSQL per turn (fewer JSONB bytes per INSERT)
- Analytics: significantly less data read per query scanning `TurnEvent` rows; query time should fall roughly in proportion to row size reduction
- Disk: smaller table and indexes, better cache hit rate for the same shared_buffers

### How to test

1. Run `ingest_isolation` benchmark and compare throughput
2. Run `national_medium` benchmark and compare analytics endpoint latency (turn_insights, analytics)
3. Verify replays still work for hot-week runs (those still have `TurnEvent` rows and the archive)
4. Verify replays still work for a compacted run by reading the archive file directly

---

## Optimization 4 — Remove `chosen_card` from TurnEvent

**Type:** Schema migration. Medium analytics impact. Requires replay archive pre-check.

### Problem

`TurnEvent.chosen_card` stores the full card JSON object (~200 bytes). All analytically useful information from this field is already extracted into three dedicated indexed scalar columns at ingest time:

- `chosen_card_type` (CharField, db_index=True)
- `chosen_card_family` (CharField, db_index=True)
- `chosen_card_tile_type` (IntegerField, db_index=True)

The raw `chosen_card` JSON is only needed to reconstruct the exact card object for replay. Replay archives store the full payload.

### Prerequisite

Same as Optimization 3: verify replay archives are complete for all compacted weeks before removing this column.

### Fix

1. Create a Django migration removing `chosen_card` from `TurnEvent`
2. Remove from `models.py`
3. Remove from `TurnEventInputSerializer` and `TurnEventSerializer` in `serializers.py`
4. Remove from `UnityTurnEventSerializer` in `serializers.py` (the `chosenCard` field is already normalized by the Unity serializer; the normalized dict entry can be dropped from `normalize_unity_run_ingestion_payload`)
5. Remove from the ingest view where `TurnEvent` objects are constructed
6. Verify no analytics code reads `chosen_card` directly (grep `chosen_card` excluding the three scalar columns)

**Files to change:**
- `DigitMilePanel/digitmileapi/models.py`
- `DigitMilePanel/digitmileapi/serializers.py`
- `DigitMilePanel/digitmileapi/run_ingestion.py`
- `DigitMilePanel/digitmileapi/views.py`
- New migration file

### Expected benefit

- ~200 bytes less per `TurnEvent` row
- Reduced I/O for analytics queries scanning `TurnEvent`
- Less Python work during ingest: `_normalize_cards_for_ingestion()` and `_extract_card_metadata()` can be simplified since the full card JSON no longer needs to be stored — only the three extracted scalar values need to be derived and stored

### How to test

Same as Optimization 3. Additionally: confirm card-type and card-family analytics still return correct data (they depend on the scalar columns, not the JSON, so should be unaffected).

---

## Optimization 5 — Remove `game_map` from Run

**Type:** Schema migration. Low ingest impact. Requires replay archive pre-check.

### Problem

`Run.game_map` stores the list of map tile objects for the run (~30 tiles × ~50 bytes JSON = ~1,500 bytes per run). This field is only used for replay. The replay archive already stores the full run payload including the map.

Analytics queries never access `game_map`. However, `Run` rows are joined in many analytics queries, and any `SELECT *` (or ORM fetch without `defer`) pulls this JSONB unnecessarily.

### Prerequisite

Same as Optimizations 3 and 4. This migration should be applied after 3 and 4 since it is lower impact and requires the same replay archive verification.

### Fix

1. Create a Django migration removing `game_map` from `Run`
2. Remove from `models.py`
3. Remove from `RunSerializer` in `serializers.py`
4. Remove from `UnityRunEventSerializer` (`gameMap` field) in `serializers.py`
5. Remove from `normalize_unity_run_ingestion_payload` in `run_ingestion.py`
6. Remove from the ingest view where `Run.objects.create()` is called
7. Grep for any template or view that reads `run.game_map` for display purposes

**Files to change:**
- `DigitMilePanel/digitmileapi/models.py`
- `DigitMilePanel/digitmileapi/serializers.py`
- `DigitMilePanel/digitmileapi/run_ingestion.py`
- `DigitMilePanel/digitmileapi/views.py`
- New migration file

### Expected benefit

- ~1,500 bytes less per `Run` row
- Modestly smaller `Run` table; better cache hit rate for analytics queries that join `Run`
- Slightly less data written per ingest request

### How to test

Run `ingest_isolation` benchmark and compare. Verify replay still works for both hot and archived runs.

---

## Implementation order and benchmarking protocol

Apply optimizations strictly in this order. After each one, push a new backend image and run `ingest_isolation` on the server. Record the key numbers before moving to the next.

| Step | Optimization | Migration? | Key metric to compare |
|---|---|---|---|
| 1 | Double student check | No | `ingest_isolation` avg latency, req/sec |
| 2 | Skip canonical re-validation | No | `ingest_isolation` req/sec, backend CPU avg |
| 2b | Re-run `national_medium` | — | throughput, backend CPU avg, analytics latency |
| 3 | Drop `offered_cards`, `bot_positions_*` | Yes | `national_medium` analytics p95, `ingest_isolation` req/sec |
| 4 | Drop `chosen_card` | Yes | `ingest_isolation` req/sec, analytics p95 |
| 5 | Drop `game_map` | Yes | `ingest_isolation` req/sec |
| 5b | Final `national_medium` run | — | Full comparison against baseline |

### Baseline numbers to beat (current state, 2026-03-18)

From `national_medium` with PgBouncer + 5 workers:

| Metric | Value |
|---|---|
| Actual throughput | 16.49 req/sec |
| Drop rate | 55.25% |
| Avg latency | 17,883ms |
| DB CPU avg | 49.21% |
| Backend CPU avg | 114.14% |

Target after all optimizations: meaningfully higher throughput and lower backend CPU avg on the same 2 vCPU hardware. Reaching 35 RPS on this server is unlikely without a hardware upgrade, but closing the gap from 16.5 → 22–25 RPS is realistic from the code changes alone.

---

## Replay archive safety policy

Optimizations 3, 4, and 5 permanently remove data from live database rows. Before each migration:

1. Run the archive verification shell script above for all compacted weeks
2. Spot-check 3–5 replay archives by actually reading them: `docker exec digitmile-backend python manage.py shell` → load archive path → decompress and parse
3. Only proceed if all compacted-week archives are in `READY` status with no verification errors

If any archive is missing or broken, fix it before running the migration. The live JSONB columns are the only other copy of that data.

Hot-week runs (not yet compacted) still have their data in the live `TurnEvent` rows, so removing the columns from the schema would also remove hot-week replay data. If replay of hot-week runs is a product feature that must work, consider one of:
- Compacting all existing hot weeks before applying the migration
- Writing the replay data to archive at ingest time (rather than at compaction time) before removing the columns
