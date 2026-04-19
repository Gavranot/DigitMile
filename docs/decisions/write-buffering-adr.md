# ADR — Redis Write-Buffered Ingest

**Status:** Accepted and implemented.
**Original plan date:** 2026-03-25. **Implemented on branch:** `feat/optimizations`.

## Context

Before this change, `POST /panel/api/runs/ingest/` performed the entire persistence sequence synchronously inside a `transaction.atomic()` block:

1. `Run.objects.create()` — 1 INSERT.
2. `TurnEvent.objects.bulk_create()` — 1 INSERT (≈30 rows).
3. `SpecialTileTrigger.objects.bulk_create()` — 1 INSERT if triggers exist.

On a 2-vCPU production host with 5 Gunicorn workers behind PgBouncer (transaction pooling), each request blocked a worker for ~40–50 ms waiting on PostgreSQL. Throughput capped at ~16–18 req/s. The national-medium benchmark target is 40 req/s.

Earlier code optimizations (rollup-only analytics, Redis caching of dashboard reads, django-ninja + Pydantic v2 validation) had reduced DB and CPU pressure elsewhere but did not move ingest throughput — the bottleneck was the synchronous DB write itself.

## Decision

Decouple validation from persistence. The ingest request validates the payload, pushes the canonical JSON onto a Redis list, and returns `202 Accepted`. A separate `flusher` worker pops batches from Redis and performs the three bulk inserts in one transaction.

```
Unity / k6          Gunicorn workers              Redis              Flusher
  |                      |                          |                   |
  |--- POST /ingest ---->|                          |                   |
  |                      |-- validate (Pydantic) -->|                   |
  |                      |-- LPUSH ingest_buffer -->|                   |
  |<--- 202 Accepted ----|                          |                   |
  |                                                 |<-- LRANGE+LTRIM --|
  |                                                 |                   |
  |                                                 |   bulk_create     |
  |                                                 |   Run + Turn +    |
  |                                                 |   Trigger         |
  |                                                 |   (1 txn/batch)   |
```

## What shipped

### Ingest path — `DigitMilePanel/digitmileapi/ingest_router.py`

`ingest_run()` keeps the upfront work (benchmark reference-time header parsing, JSON parse, Unity-vs-canonical payload detection, Pydantic validation, student existence check, idempotency check, recording-window check). After all of that passes, it does:

```python
_redis.lpush(settings.INGEST_BUFFER_REDIS_KEY, json.dumps(data))
return JsonResponse({"message": "Run accepted", "run_id": str(run_id)}, status=202)
```

The `transaction.atomic()` block and all `Run` / `TurnEvent` / `SpecialTileTrigger` imports moved out of the request path.

### Flusher — `DigitMilePanel/digitmileapi/management/commands/flush_ingest_buffer.py`

Long-running Django management command. Runs in a loop:

1. `pipeline: LRANGE ingest_buffer 0 (batch-1); LTRIM ingest_buffer batch -1` — atomically pops up to `--batch-size` items.
2. Deduplicates within the batch **and** against already-persisted `Run` IDs with a single `Run.objects.filter(id__in=...).values_list("id", flat=True)`.
3. `Run.bulk_create(...)` → `TurnEvent.bulk_create(...)` → `SpecialTileTrigger.bulk_create(...)` in one `transaction.atomic()`.
4. On any exception, items are `RPUSH`-ed back to the queue tail to be retried on the next iteration; no item is lost.

Flags: `--batch-size` (default 50), `--sleep-ms` (default 100). Both are also exposed via env vars `INGEST_BUFFER_BATCH_SIZE` and `INGEST_BUFFER_SLEEP_MS` in `settings.py`.

### Deployment — `docker-compose.yml`

The `flusher` service reuses the backend image and runs `python manage.py flush_ingest_buffer`. It has the same `.env` and Redis URL as `backend`, and `restart: always`. `docker-compose.prod.yml` pins it to the same Docker Hub image the backend uses.

### Settings — `DigitMilePanel/digitmile/settings.py`

```python
INGEST_BUFFER_REDIS_KEY = "ingest_buffer"
INGEST_BUFFER_BATCH_SIZE = int(os.getenv("INGEST_BUFFER_BATCH_SIZE", "50"))
INGEST_BUFFER_SLEEP_MS = int(os.getenv("INGEST_BUFFER_SLEEP_MS", "100"))
```

### Dependency surface

No new PyPI packages. `redis` (the client library) is already a transitive dependency of `django-redis` and is imported directly in both `ingest_router.py` and the flusher command.

## Key design choices

- **`lrange` + `ltrim` pipeline, not `brpop` per item.** Amortizes round-trips across a batch; one atomic pop per batch, not per run.
- **Batch-level deduplication.** A single `Run.objects.filter(id__in=run_ids)` covers the whole batch.
- **Three sequential `bulk_create` calls inside one transaction.** Same number of DB round-trips as the pre-buffer code, but now amortized across ~50 runs instead of charged to every request.
- **Retry on failure, not drop.** The flusher `RPUSH`-es failed items back to the tail of the queue. Workers never see persistence errors.
- **Shared Redis instance with Django cache.** `INGEST_BUFFER_REDIS_KEY` lives on the same Redis DB (`/1`) that `django-redis` uses for the dashboard cache.

## Outcome

Worker time per ingest dropped from ~50 ms (DB round-trips) to ~3 ms (Redis `LPUSH`). Backend throughput is no longer bounded by PostgreSQL per-request latency; the ingest bottleneck moves to the flusher batch cadence, which is tunable via `--batch-size` / `--sleep-ms`. The remaining headroom for national-medium load is now on the 2-vCPU CPU ceiling — see `docs/decisions/hardware-sizing.md` and `docs/decisions/ingest-optimization-plan.md` for the follow-up optimizations.

## Operational notes

- The flusher is **required** in production. If it stops, `ingest_buffer` grows without bound and data persistence stalls. Monitor: `LLEN ingest_buffer`.
- Data in the buffer is not persistent across a Redis flush. Redis is configured with `--appendonly yes --appendfsync everysec` in `docker-compose.yml:31`, which bounds the loss window to ~1 s of accepted writes on a hard crash. Acceptable for game telemetry, not for transactional data.
- The `202 Accepted` response means "validated and queued", not "committed". Clients that need write-through confirmation would require a different endpoint; none currently do.
