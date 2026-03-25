# Write Buffering Implementation Plan

## Problem

The ingest endpoint (`POST /panel/api/runs/ingest/`) performs 2-3 synchronous DB round-trips per request inside `transaction.atomic()`:

1. `Run.objects.create()` — 1 INSERT
2. `TurnEvent.objects.bulk_create()` — 1 INSERT (batch of ~30 rows)
3. `SpecialTileTrigger.objects.bulk_create()` — 1 INSERT (batch, if triggers exist)

Each Gunicorn worker is blocked for ~40-50ms waiting on PostgreSQL (via PgBouncer). With 5 workers and the backend CPU pinned at ~110% on 2 vCPUs, throughput caps at ~17-18 req/s. Benchmark target is 40 req/s.

Software optimizations already applied (rollup-only analytics, Redis caching, django-ninja + Pydantic v2 validation) reduced DB and CPU pressure but did not improve throughput because the bottleneck is synchronous DB writes, not validation or analytics.

## Solution

Decouple validation from persistence. The ingest endpoint validates, pushes the canonical payload to a Redis list, and returns `202 Accepted`. A separate flusher process reads batches from the Redis list and bulk-inserts them into PostgreSQL in a single transaction per batch.

**Expected impact:** Worker time per ingest request drops from ~50ms to ~3ms (Redis LPUSH). At 5 workers, theoretical ingest throughput exceeds 100 req/s.

---

## Architecture

```
Unity / k6          Gunicorn workers              Redis              Flusher
  |                      |                          |                   |
  |--- POST /ingest ---->|                          |                   |
  |                      |-- validate (Pydantic) -->|                   |
  |                      |-- LPUSH ingest_queue --->|                   |
  |<--- 202 Accepted ----|                          |                   |
  |                                                 |<-- LRANGE+LTRIM --|
  |                                                 |                   |
  |                                                 |     bulk_create   |
  |                                                 |     Run + Turn +  |
  |                                                 |     Trigger       |
  |                                                 |     (1 txn/batch) |
```

---

## Files to change

### 1. `DigitMilePanel/digitmileapi/ingest_router.py` (MODIFY)

**Current state:** Lines 161-291 contain the `transaction.atomic()` block that creates Run, TurnEvent, and SpecialTileTrigger objects synchronously. This is inside the `ingest_run()` ninja router function.

**Change:** Replace lines 161-291 (the `# Persist` section through end of function) with:

```python
import redis as redis_client

# Get Redis connection (same instance used for Django cache)
_redis = redis_client.from_url(settings.CACHES["default"]["LOCATION"])
INGEST_QUEUE_KEY = "ingest_buffer"

# ... inside ingest_run(), after validation and recording window check:

# Push validated canonical dict to Redis buffer
_redis.lpush(INGEST_QUEUE_KEY, json.dumps(data))

_log_run_ingest_event(
    logging.INFO,
    "run_ingest_queued",
    run_id=run_id,
    student_id=data["student_id"],
)

return JsonResponse(
    {"message": "Run accepted", "run_id": str(run_id)},
    status=202,
)
```

**What stays unchanged (lines 56-160):**
- Benchmark reference time header parsing
- JSON body parsing
- Unity vs canonical payload detection
- Pydantic v2 validation (`UnityIngestPayload` / `CanonicalIngestPayload`)
- Student existence check (`Student.objects.filter(pk=...).exists()`)
- Duplicate run_id check (`Run.objects.filter(id=run_id).exists()`)
- Recording window check (returns 409 synchronously)

**What gets removed:**
- `from django.db import IntegrityError, transaction` (no longer needed)
- `from .models import Run, SpecialTileTrigger, TurnEvent` (moved to flusher)
- `from .views import _extract_card_metadata, _normalize_cards_for_ingestion` (moved to flusher)
- The entire `try: with transaction.atomic(): ...` block (lines 162-291)
- The `IntegrityError` and generic `Exception` handlers

**New imports needed:**
- `import redis as redis_client` (the `redis` PyPI package, pulled in by `django-redis`)

**Note on Redis connection:** `django-redis` already depends on the `redis` package. The `CACHES["default"]["LOCATION"]` env var points to `redis://benchmark-redis:6379/1` in Docker. Use that same URL for the buffer connection.

---

### 2. `DigitMilePanel/digitmileapi/management/commands/flush_ingest_buffer.py` (NEW FILE)

New Django management command. Long-running process that reads from the Redis list and bulk-inserts into PostgreSQL.

**Core logic:**

```python
"""
Usage: python manage.py flush_ingest_buffer
       python manage.py flush_ingest_buffer --batch-size 100 --sleep-ms 50

Runs in a loop. Reads up to --batch-size items from the Redis ingest buffer,
bulk-creates Run + TurnEvent + SpecialTileTrigger objects in one transaction,
then sleeps for --sleep-ms milliseconds before the next iteration.
"""

import json
import time
import logging

import redis as redis_client
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from digitmileapi.models import Run, TurnEvent, SpecialTileTrigger
from digitmileapi.run_ingestion import unix_ms_to_datetime
from digitmileapi.views import _normalize_cards_for_ingestion, _extract_card_metadata

logger = logging.getLogger(__name__)

INGEST_QUEUE_KEY = "ingest_buffer"  # Must match ingest_router.py

class Command(BaseCommand):
    help = "Flush the Redis ingest buffer into PostgreSQL in batches."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--sleep-ms", type=int, default=100)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        sleep_s = options["sleep_ms"] / 1000.0
        r = redis_client.from_url(settings.CACHES["default"]["LOCATION"])
        logger.info("Flusher started: batch_size=%d, sleep_ms=%d", batch_size, options["sleep_ms"])

        while True:
            flushed = self._flush_batch(r, batch_size)
            if flushed == 0:
                time.sleep(sleep_s)

    def _flush_batch(self, r, batch_size):
        # Atomic pop of up to batch_size items
        pipe = r.pipeline()
        pipe.lrange(INGEST_QUEUE_KEY, 0, batch_size - 1)
        pipe.ltrim(INGEST_QUEUE_KEY, batch_size, -1)
        results = pipe.execute()
        raw_items = results[0]

        if not raw_items:
            return 0

        payloads = [json.loads(item) for item in raw_items]
        # ... see "Flusher bulk insert logic" section below
```

**Flusher bulk insert logic (the tricky part):**

The FK chain is: `SpecialTileTrigger.turn → TurnEvent` and `TurnEvent.run → Run`. You must create objects top-down and retrieve auto-generated PKs at each level.

```python
def _flush_batch(self, r, batch_size):
    # ... (pop items as above) ...

    payloads = [json.loads(item) for item in raw_items]

    # 1. Deduplicate within batch + against DB
    run_ids = [p["run_id"] for p in payloads]
    existing_ids = set(
        Run.objects.filter(id__in=run_ids).values_list("id", flat=True)
    )
    # Also deduplicate within the batch itself (keep first occurrence)
    seen = set()
    unique_payloads = []
    for p in payloads:
        if p["run_id"] not in existing_ids and p["run_id"] not in seen:
            seen.add(p["run_id"])
            unique_payloads.append(p)

    if not unique_payloads:
        return len(payloads)  # All duplicates, nothing to insert

    try:
        with transaction.atomic():
            # 2. Bulk-create Run objects
            run_objects = [
                Run(
                    id=p["run_id"],
                    student_id=p["student_id"],
                    level=p["level"],
                    player_won=p["player_won"],
                    score=p["score"],
                    place=p.get("place", 1 if p["player_won"] else 4),
                    elapsed_ms=p["elapsed_ms"],
                    correct_moves=p["correct_moves"],
                    wrong_moves=p["wrong_moves"],
                    game_map=p.get("game_map", []),
                    map_version=p.get("map_version", "1"),
                    bot_version=p.get("bot_version", "1"),
                    rng_seed=p.get("rng_seed"),
                )
                for p in unique_payloads
            ]
            created_runs = Run.objects.bulk_create(run_objects)
            run_by_id = {r.id: r for r in created_runs}

            # 3. Bulk-create TurnEvent objects (across all runs in the batch)
            all_turn_events = []
            # Map: (run_id, turn_index) -> list of trigger dicts
            all_trigger_sources = {}

            for p in unique_payloads:
                run_obj = run_by_id[p["run_id"]]
                for event_data in p.get("turn_events", []):
                    timestamp_played = unix_ms_to_datetime(
                        event_data["timestamp_played_unix_ms"]
                    )
                    chosen_card, offered_cards = _normalize_cards_for_ingestion(
                        event_data.get("chosen_card"),
                        event_data.get("offered_cards"),
                    )
                    ctype, cfamily, ctile = _extract_card_metadata(chosen_card)

                    te = TurnEvent(
                        run=run_obj,
                        turn_index=event_data["turn_index"],
                        timestamp_played=timestamp_played,
                        chosen_card=chosen_card,
                        chosen_card_type=ctype,
                        chosen_card_family=cfamily,
                        chosen_card_tile_type=ctile,
                        offered_cards=offered_cards,
                        was_correct=event_data["was_correct"],
                        tile_before_index=event_data["tile_before_index"],
                        tile_before_type=event_data["tile_before_type"],
                        tile_after_index=event_data["tile_after_index"],
                        place_before=event_data["place_before"],
                        place_after=event_data["place_after"],
                        bot_positions_before=event_data.get("bot_positions_before", []),
                        bot_positions_after=event_data.get("bot_positions_after", []),
                        card_decision_time_ms=event_data["card_decision_time_ms"],
                        offered_numbers=event_data.get("offered_numbers", []),
                        chosen_number=event_data.get("chosen_number"),
                        number_decision_time_ms=event_data.get("number_decision_time_ms"),
                    )
                    all_turn_events.append(te)

                    triggers = event_data.get("special_tile_triggers", [])
                    if triggers:
                        all_trigger_sources[(p["run_id"], event_data["turn_index"])] = triggers

            created_turns = TurnEvent.objects.bulk_create(all_turn_events)

            # 4. Build trigger objects using the created TurnEvent PKs
            turn_lookup = {(te.run_id, te.turn_index): te for te in created_turns}

            all_triggers = []
            for (run_id, turn_index), trigger_list in all_trigger_sources.items():
                te = turn_lookup[(run_id, turn_index)]
                for td in trigger_list:
                    all_triggers.append(
                        SpecialTileTrigger(
                            turn=te,
                            chain_index=td["chain_index"],
                            special_tile_index=td["special_tile_index"],
                            special_tile_type=td["special_tile_type"],
                            effect_delta_tiles=td["effect_delta_tiles"],
                            target_tile_index=td["target_tile_index"],
                            target_tile_type=td["target_tile_type"],
                            place_before=td["place_before"],
                            place_after=td["place_after"],
                        )
                    )

            if all_triggers:
                SpecialTileTrigger.objects.bulk_create(all_triggers)

        logger.info(
            "Flushed %d runs (%d turns, %d triggers)",
            len(created_runs), len(created_turns), len(all_triggers),
        )
        return len(payloads)

    except Exception:
        logger.exception("Flusher batch failed — items returned to queue")
        # Push failed items back to the RIGHT side of the queue (tail)
        # so they retry on the next iteration.
        pipe = r.pipeline()
        for item in raw_items:
            pipe.rpush(INGEST_QUEUE_KEY, item)
        pipe.execute()
        return 0
```

**Key design decisions in the flusher:**

- `lrange` + `ltrim` in a pipeline atomically pops a batch. No item is lost even if the flusher crashes between read and insert — on failure, items are pushed back to the queue tail.
- Deduplication is done with a single `Run.objects.filter(id__in=...).values_list(...)` query for the entire batch (1 query for 50 runs, instead of 50 queries).
- The FK chain `Run → TurnEvent → SpecialTileTrigger` requires 3 sequential `bulk_create` calls inside one transaction. This is the same number of DB operations as the current per-request code, but amortized over 50 runs.
- The `turn_lookup` dict uses `(run_id, turn_index)` as key to correctly map triggers to the right TurnEvent across multiple runs in the batch.

---

### 3. `DigitMilePanel/requirements.txt` (NO CHANGE)

`redis` (the PyPI package) is already a transitive dependency of `django-redis`. No new package needed.

Verify: `pip show django-redis` shows `Requires: django, redis`.

---

### 4. `DigitMilePanel/digitmile/settings.py` (MINOR ADDITION)

Add a setting for the buffer queue key and flusher defaults. Optional but useful for config consistency:

```python
# Write buffer settings
INGEST_BUFFER_REDIS_KEY = "ingest_buffer"
INGEST_BUFFER_BATCH_SIZE = int(os.getenv("INGEST_BUFFER_BATCH_SIZE", "50"))
INGEST_BUFFER_SLEEP_MS = int(os.getenv("INGEST_BUFFER_SLEEP_MS", "100"))
```

Both `ingest_router.py` and `flush_ingest_buffer.py` should import the queue key from settings rather than hardcoding it.

**Redis persistence:** The current Redis services (both `docker-compose.yml` and `benchmarks/docker-compose.benchmark.yml`) use ephemeral storage. The write buffer requires persistence to survive Redis restarts. Add a command override:

```yaml
# In both docker-compose files, on the redis service:
command: redis-server --appendonly yes --appendfsync everysec
volumes:
  - redis_data:/data
```

And add `redis_data:` to the `volumes:` section at the bottom.

This is critical for production. For benchmarking only, it's optional — a Redis restart mid-benchmark is unlikely and the benchmark data is disposable.

---

### 5. `docker-compose.yml` (ADD FLUSHER SERVICE)

Add a new service after the `backend` service:

```yaml
  # Flusher — reads from Redis ingest buffer and bulk-writes to PostgreSQL.
  # Uses the same backend image, just a different entrypoint.
  flusher:
    build:
      context: ./DigitMilePanel
      dockerfile: Dockerfile.compose
    container_name: digitmile-flusher
    env_file:
      - .env
    environment:
      REPLAY_ARCHIVE_ROOT: /var/lib/digitmile/replay-archives
      REDIS_URL: redis://redis:6379/1
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
      redis:
        condition: service_healthy
    networks:
      - digitmile-network
    command: python manage.py flush_ingest_buffer
    # No healthcheck needed — if it dies, runs accumulate in Redis
    # and get flushed when it restarts. Consider restart: always.
    restart: always
```

The flusher connects directly to `pgbouncer` (via `DB_HOST` from `.env`) just like the backend.

---

### 6. `benchmarks/docker-compose.benchmark.yml` (ADD BENCHMARK FLUSHER)

Add a flusher service for the benchmark stack:

```yaml
  benchmark-flusher:
    image: gashmurble/digitmile-backend:prod-latest
    env_file:
      - ../.env
    environment:
      DB_HOST: benchmark-pgbouncer
      DB_NAME: ${BENCHMARK_DB_NAME:-digitmile_benchmark}
      DB_USER: ${BENCHMARK_DB_USER:-digitmile}
      DB_PASS: ${BENCHMARK_DB_PASS:-benchmark-pass}
      DB_PORT: 5432
      REDIS_URL: redis://benchmark-redis:6379/1
    depends_on:
      benchmark-db:
        condition: service_healthy
      benchmark-pgbouncer:
        condition: service_started
      benchmark-redis:
        condition: service_healthy
    command: python manage.py flush_ingest_buffer --batch-size 50 --sleep-ms 100
    networks:
      - benchmark-network
    restart: always
```

---

### 7. `benchmarks/k6/ingest.js` and `benchmarks/k6/mixed_weekly_cycle.js` (MINOR)

Update the success check to accept `202`:

**`ingest.js` line 71:**
```javascript
// Before:
"open-week ingest accepted": (value) => [200, 201].includes(value.status),
// After:
"open-week ingest accepted": (value) => [200, 201, 202].includes(value.status),
```

**`mixed_weekly_cycle.js` line 203:**
```javascript
// Before:
check(response, { "mixed open-week ingest accepted": (value) => [200, 201].includes(value.status) });
// After:
check(response, { "mixed open-week ingest accepted": (value) => [200, 201, 202].includes(value.status) });
```

---

### 8. `benchmarks/run_scenario.py` (OPTIONAL)

Add flusher container to the resource-usage tracking so its CPU/memory appears in benchmark reports.

In the section where `runtime_container_ids` is built (after resolving backend, db, pgbouncer, redis container IDs), add:

```python
flusher_container_id = compose_service_container_id(project_name, "benchmark-flusher")
if flusher_container_id:
    runtime_container_ids["flusher"] = flusher_container_id
```

Also consider adding a post-benchmark check that the Redis buffer is fully drained before collecting final metrics:

```python
# After k6 finishes, wait for buffer to drain
for _ in range(60):  # up to 6 seconds
    queue_len = int(compose_exec(project_name, "benchmark-redis", "redis-cli", "llen", "ingest_buffer").stdout.strip())
    if queue_len == 0:
        break
    time.sleep(0.1)
log_step(f"Ingest buffer drained (queue length: {queue_len})")
```

---

## Sequence of changes (implementation order)

1. **Create `flush_ingest_buffer.py`** management command with the full flusher logic. Test it independently by manually pushing JSON payloads to Redis and verifying DB inserts.

2. **Modify `ingest_router.py`** to push to Redis instead of writing to DB. The function shrinks from 291 lines to ~80 lines.

3. **Update k6 scripts** to accept 202 status.

4. **Add flusher services** to both docker-compose files.

5. **Optionally** add Redis persistence (`appendonly yes`) and flusher resource tracking to the benchmark script.

6. **Build, push, and benchmark.**

---

## Risk mitigations

| Risk | Mitigation |
|---|---|
| Redis restart loses buffered runs | Add `appendonly yes` + volume mount. For benchmarks this is non-critical. |
| Flusher crashes silently | `restart: always` in docker-compose. Failed batches are pushed back to queue tail. |
| Duplicate runs in batch | Single `Run.objects.filter(id__in=...)` query deduplicates before insert. `bulk_create` with explicit PKs raises `IntegrityError` on race — caught by the `except` block which retries. |
| Rollup reads stale data | Flusher drain latency is ~100ms. Nightly rollups are unaffected. If real-time visibility matters, add a `manage.py drain_ingest_buffer` call before rollup jobs. |
| Unity client rejects 202 | Check C# code. If it only accepts 200/201, change the buffered response to return `201` (a white lie — the data is accepted and will be persisted). The run_id is known at response time. |

---

## Response contract change

| Field | Current (201) | Buffered (202) |
|---|---|---|
| `message` | "Run ingested successfully" | "Run accepted" |
| `run_id` | Present | Present (known at validation time) |
| `turn_events_count` | Present | **Absent** (not yet inserted) |
| `triggers_count` | Present | **Absent** (not yet inserted) |

If the Unity client or any consumer relies on `turn_events_count` / `triggers_count`, those fields can be computed from the validated payload before pushing to Redis (count the turn_events and triggers lists). They won't reflect DB reality but they'll match what will be inserted.

---

## What NOT to change

- **`ingest_schemas.py`** — Pydantic v2 schemas stay as-is. Validation happens identically.
- **`views.py`** — The old `RunIngestionView` class is dead code (URL removed). Leave it or delete it; it doesn't affect anything.
- **`urls.py` (both)** — Routing is already correct. Ninja handles `/panel/api/runs/ingest/`.
- **`run_ingestion.py`** — `normalize_unity_run_ingestion_payload` stays as-is. Used by the router before pushing to Redis.
- **Analytics, rollups, dashboard** — Completely unaffected.
