# Ingestion Pipeline Performance Audit

Scope: the write path from HTTP to Postgres for `/panel/api/runs/ingest/`. Read/dashboard paths are out of scope.

---

## 1. Current state summary

HTTP request flow:

1. Client POSTs JSON Unity payload to `/panel/api/runs/ingest/`
   (`DigitMile/nginx-proxy/nginx.conf.production:59` routes `/panel/` to `upstream backend`).
2. Gunicorn **WSGI sync**, 5 workers (`DigitMilePanel/Dockerfile.compose:30`,
   `docker-compose.yml:100`). django-ninja is mounted on WSGI — async endpoints don't apply.
3. `digitmile/urls.py:29-30` mounts `NinjaAPI` at `panel/api/`.
4. `digitmileapi/ingest_router.py:55 ingest_run(request)` — a **sync** function:
   - `json.loads(request.body)` (stdlib) — line 69.
   - Pydantic `UnityIngestPayload.model_validate(body)` — line 76. The `@model_validator` in
     `ingest_schemas.py:91-120` walks all turns (sequentiality checks, moves reconciliation).
   - **DB roundtrip 1**: `Student.objects.filter(pk=...).exists()` — line 88.
   - `normalize_unity_run_ingestion_payload(unity_payload.model_dump())` — walks turns/triggers
     again to rename camelCase → snake_case (`run_ingestion.py:53-117`).
   - **DB roundtrip 2**: `Run.objects.filter(id=run_id).exists()` — line 119.
   - Recording-window check (pure-Python, tz math).
   - `_redis.lpush(INGEST_BUFFER_REDIS_KEY, json.dumps(data))` — sync redis client, no pipelining,
     single global key.
   - Per-request `logger.info("run_ingest_queued", …)` — line 163.
5. Response: `JsonResponse(..., status=202)`.

Flusher flow (`management/commands/flush_ingest_buffer.py`):

1. Single process loop; `LRANGE 0 N-1` + `LTRIM N -1` in one pipeline (line 61-64). Batch size 50.
   Sleeps 100 ms when empty. **No time-based flush trigger** — batch only fires on size.
2. `json.loads` each item.
3. Dedup against DB: `Run.objects.filter(id__in=run_ids).values_list("id", flat=True)`.
4. Inside `transaction.atomic()`:
   - Build `Run(...)` model instances → `Run.objects.bulk_create(...)` (line 110).
   - For every queued run, walk turns → call `_normalize_cards_for_ingestion` +
     `_extract_card_metadata` (parses `[CardData: …]` string per card) → build `TurnEvent(...)`.
   - `TurnEvent.objects.bulk_create(...)` (line 165).
   - Build `SpecialTileTrigger(...)` list → `bulk_create(...)`.
5. On any exception, the whole batch is RPUSHed back to the tail (line 204-207). There is **no
   dead-letter / poison-pill handling** — a malformed item permanently stalls the queue.

Schema: one wide `Run` table plus two child tables. All three use Python-generated prefixed
CharField PKs (`models.py:42-54`). No declarative partitioning. 10+ indexes on the hot tables.

What's already done well: Redis write-buffer in front of PG, PgBouncer transaction pooling with
`CONN_MAX_AGE=0` + `DISABLE_SERVER_SIDE_CURSORS=True`, `synchronous_commit=off`, `bulk_create` under
`transaction.atomic`, pipelined LRANGE+LTRIM, in-flusher dedup.

---

## 2. Identified bottlenecks

Ranked by likely impact at 2,400 RPS on 2 vCPU / 4 GB. "(suspected)" = needs measurement before
sizing.

1. **HTTP ingest is blocked by 2 synchronous PG roundtrips per request**
   (`ingest_router.py:88 Student.exists`, `:119 Run.exists`).
   With 5 sync workers, each blocked ~2–5 ms on PG per request, the theoretical ceiling is around
   1,000–2,500 RPS before workers saturate — right where the stated peak load sits. (suspected —
   measure with `pg_stat_statements` on these two queries.)

2. **WSGI sync serving of an I/O-bound endpoint.** `gunicorn --workers 5` on 2 vCPUs means
   at most 5 in-flight ingest calls at once (`docker-compose.yml:100`). The work is
   almost entirely I/O (redis + PG), so an async runtime would hit the same hardware far harder.
   django-ninja supports async endpoints natively; only the WSGI shim blocks it.

3. **Write amplification from redundant / unjustified indexes on hot child tables.**
   - `TurnEvent.turn_run_index_idx (run, turn_index)` duplicates the unique constraint
     `unique_turn_per_run (run, turn_index)` (`models.py:556-567`). Two B-trees per row.
   - `chosen_card_type`, `chosen_card_family`, `chosen_card_tile_type` each carry
     `db_index=True` (`models.py:512-529`). Three extra B-tree inserts per row × ~8.4 M rows/week.
     These look dashboard-driven; moving them behind a rollup eliminates writes entirely.
   - `SpecialTileTrigger` has `trigger_turn_chain_idx (turn, chain_index)` *plus* the unique
     constraint `unique_chain_per_turn (turn, chain_index)` (`models.py:604-614`) — duplicate —
     and separate `trigger_tile_index_idx`, `trigger_tile_type_idx` whose write-path justification
     isn't visible from the ingestion code.

4. **Per-request `LocaleMiddleware` and full Django middleware stack on the ingest URL**
   (`settings.py:77-89`). `LocaleMiddleware` parses `Accept-Language` and activates a translation
   on every request. `SessionMiddleware` + `AuthenticationMiddleware` also run, even though the
   endpoint is `auth=None`. Costs milliseconds per request at 2,400 RPS. (suspected magnitude;
   measure by route-specific middleware bypass.)

5. **`DEBUG=True` is the default in production** (`settings.py:38` —
   `os.getenv("DEBUG", "True") == "True"`). If the prod `.env` forgets to set `DEBUG=False`,
   SQL query logging stays on and memory grows unbounded. Confirm `.env` in prod sets
   `DEBUG=False`; fix the default regardless.

6. **`Run.id` is `CharField(max_length=36)`** stored as text (`models.py:457-460`), so every
   `TurnEvent.run_id` FK is a 36-byte string. Native `UUIDField` is 16 bytes — halves the B-tree
   size of every run-keyed index on `TurnEvent` (~8 M rows/week) and `SpecialTileTrigger`, and makes
   FK lookups faster. Also removes the Python PK generation cost on `bulk_create`.

7. **`TurnEvent.id` collisions become non-negligible at scale.** `generate_turn_event_id` uses
   `uuid.uuid4().hex[:12]` → 48 bits of entropy. Birthday-paradox estimate: at ~8.4 M rows/week, P(collision)
   ≈ 0.01 %/week; cumulative over a semester (~100–150 M rows) it climbs into the 5 %+ range. When it
   hits, `bulk_create` aborts the whole batch. (`models.py:47-54`, same for
   `SpecialTileTrigger.id`.) This is a silent correctness bug that also shows up as flusher batch
   failures.

8. **`bulk_create` uses multi-row INSERT, not `COPY`.** For TurnEvent — the widest, highest-volume
   child — `COPY FROM STDIN` is 3–5× faster than multi-row INSERT at batch sizes ≥ ~500. Django
   doesn't do this; `psycopg2.copy_expert` inside the flusher would. (suspected gain; measure.)

9. **Flusher is single-process, single-queue.** One Python interpreter draining one Redis LIST.
   `lpush` on the producer side is strictly serial at the consumer. Can't parallelize because
   `LRANGE`+`LTRIM` on a LIST isn't safe for multiple consumers. Redis Streams with consumer groups
   (`XADD` / `XREADGROUP`) would enable N parallel flushers + `MAXLEN ~` for bounded backpressure.

10. **No backpressure on the Redis queue.** If the flusher falls behind,
    `ingest_buffer` grows unbounded in Redis memory (`ingest_router.py:161` just `lpush`es).
    At 2,400 RPS with a 2 KB canonical-JSON payload (estimate), one minute of flusher outage ≈
    ~290 MB of Redis memory.

11. **Per-request INFO logging.** `_log_run_ingest_event(INFO, "run_ingest_queued", …)` fires on
    every successful ingest (`ingest_router.py:163-168`), formatted and written synchronously to
    stdout by the default `StreamHandler`. At 2,400 log lines/sec with a formatter, this is a real
    CPU + context-switch cost and also blocks the worker on stdout backpressure.

12. **`game_map` is persisted in every Run row** (`models.py:470-474`). It's a per-level asset —
    redundantly transmitted and stored once per session. If `map_version` uniquely identifies the
    map, keep a `GameMap(version, tiles)` table and drop the field from `Run`. Saves Redis memory,
    JSON parse time, and hundreds of MB/semester in table bloat.

13. **`max_wal_size` is unset.** Default is 1 GB — under sustained 2,400 writes/sec the DB will
    request checkpoints, not hit timed checkpoints, causing checkpoint storms. Bump to 4–8 GB.

14. **Autovacuum defaults on `turnevent` and `specialtiletrigger`.** At ~8 M and ~2 M inserts/week,
    the default `autovacuum_vacuum_scale_factor=0.2` means vacuum rarely runs, then runs huge.
    Per-table `autovacuum_vacuum_scale_factor=0.05`, `autovacuum_vacuum_insert_scale_factor=0.02`,
    and lifted cost limits would keep it responsive.

Non-bottlenecks I looked for and didn't find:
- No N+1 on the write path.
- No synchronous signals firing on Run/TurnEvent (only `post_migrate` in `apps.py`).
- No cache invalidation chained off writes.

---

## 3. Recommended optimizations

### Do these first

#### R1. Drop `Run.exists()` in the HTTP handler; cache `Student` existence in Redis

**What:** Delete `Run.objects.filter(id=run_id).exists()` in `ingest_router.py:119` — the flusher
already deduplicates against the DB at `flush_ingest_buffer.py:74-76`, so the HTTP-side check is
redundant. Replace `Student.objects.filter(pk=...).exists()` (line 88, 109) with a Redis `SISMEMBER`
against a `students:ids` set that is refreshed on Student create/delete (small population, a few
thousand). Fallback to DB on cache miss.

**Why it matters:** Removes both PG roundtrips from the hot HTTP path. At 2,400 RPS this is ~4,800
queries/sec of saved load *and* ~2–10 ms of serialized latency off every worker slot. Should raise
the HTTP-layer ceiling meaningfully even before going async.

**Effort:** S (remove one check; write a tiny cache warmer / invalidator on Student save).

**Risk:** Student cache staleness on rapid create/delete — low for this app (students are
pre-enrolled by teachers, rarely deleted mid-lesson). Duplicate runs now only rejected at flusher
time — that's already the authoritative check anyway.

**Thesis value:** High. "Ingest endpoint PG roundtrip count: 2 → 0" is a clean before/after chart.

---

#### R2. Switch ingest to async + uvicorn + `redis.asyncio`

**What:** Change the entrypoint of the backend container (and only that container — the flusher
stays as-is) to `uvicorn digitmile.asgi:application --workers 2 --loop uvloop --http httptools`.
Convert `ingest_run` to `async def`. Use `redis.asyncio.Redis.from_url(...)` for the write buffer.
Keep Django's sync ORM out of the handler — R1 removes the two ORM calls, so the handler becomes
pure I/O (JSON parse → pydantic → redis).

**Why it matters:** With I/O-bound work, two async workers on 2 vCPUs can handle hundreds of
concurrent in-flight requests. Sync WSGI caps you at 5. Expected 3–5× throughput at the HTTP layer
under the same CPU budget; especially valuable when combined with R1 because latency per request
drops too.

**Effort:** M. Ninja already supports async handlers. Need to verify all middleware is ASGI-safe
(WhiteNoise, Corsheaders, Sessions, Locale all are) or mount the ingest router on a minimal ASGI
app with fewer middlewares (see R4).

**Risk:** Any sync code path accidentally called from the async handler blocks the event loop. The
other `/panel/` URLs (dashboards, admin) also run on ASGI and must be tested. django-admin
historically worked fine on ASGI but confirm with the admin pages.

**Thesis value:** Highest. Clean comparative chapter: sync WSGI vs async ASGI under identical
payload, RPS, and hardware. The benchmark harness in `benchmarks/k6/ingest.js` is ready-made for it.

---

#### R3. Drop unnecessary indexes on `TurnEvent` and `SpecialTileTrigger`

**What:** In a migration, drop:
- `turn_run_index_idx` on `TurnEvent(run, turn_index)` — duplicated by the unique constraint.
- `trigger_turn_chain_idx` on `SpecialTileTrigger(turn, chain_index)` — duplicated by the unique
  constraint.
- `trigger_tile_index_idx`, `trigger_tile_type_idx` — verify no dashboard query uses them (grep
  `rollup_*.py`); most likely replaceable by the rollup tables that already serve those questions.
- `chosen_card_type`, `chosen_card_family`, `chosen_card_tile_type` `db_index=True` — same check.
  The `card_type`, `card_family` rollup tables exist; hot-table indexes on raw columns look dead.

**Why it matters:** Every index drop removes ~N B-tree inserts per row inserted. At 8 M TurnEvent
rows/week, each dropped index avoids ~8 M entries/week — less WAL, less I/O, faster `bulk_create`.
Five drops × 8 M rows = ~40 M avoided index writes/week on `TurnEvent` alone.

**Effort:** S (one migration).

**Risk:** If any read path actually uses them, you'll regress a dashboard query. Run
`SELECT schemaname, relname, indexrelname, idx_scan FROM pg_stat_user_indexes ORDER BY idx_scan`
after a live week — any zero-scan index is safe to drop. For thesis purposes that's a great
measurement artefact on its own.

**Thesis value:** High. "Index audit on ingestion tables" is a textbook DB-optimisation chapter.

---

#### R4. Bypass unused middleware on the ingest URL

**What:** Split the ASGI/WSGI app so `/panel/api/runs/ingest/` is served by a minimal stack:
`SecurityMiddleware` only (or nothing). Drop `LocaleMiddleware`, `SessionMiddleware`,
`AuthenticationMiddleware`, `MessageMiddleware`, `XFrameOptionsMiddleware`, and
`WhiteNoiseMiddleware` for this endpoint — none are used. Easiest: mount Ninja at the ASGI root on
its own sub-app, behind a routing layer, so it doesn't traverse Django's MIDDLEWARE list.

**Why it matters:** Cuts per-request middleware CPU, especially `LocaleMiddleware`'s header parse
and `SessionMiddleware`'s cookie parse. Rough estimate 0.5–1.5 ms per request shaved; at 2,400 RPS
with 2 vCPUs that's meaningful (1–3 % of the total CPU budget).

**Effort:** M.

**Risk:** Low if the split is URL-based. Double-check that CORS is still applied — game may hit the
endpoint cross-origin.

**Thesis value:** Moderate. Nice micro-benchmark showing middleware overhead per request.

---

#### R5. Convert PKs to native `UUIDField` and fix the 48-bit collision risk

**What:** Migrate `Run.id`, `TurnEvent.id`, `SpecialTileTrigger.id` to native `UUIDField` (16 bytes
binary in PG). Generate via `DEFAULT gen_random_uuid()` so PK is set by the DB, not Python. Update
FKs. If the `run_`/`trn_`/`stt_` prefixes are needed for log readability, keep them only on the
printable representation (e.g. a property), not the stored column.

**Why it matters:** Halves storage of the Run PK and every FK to it. On `TurnEvent.run_id`
(~8 M × 36 bytes vs 16 bytes = ~160 MB/week saved), plus faster FK comparisons everywhere. Also
eliminates the 48-bit collision risk on TurnEvent/SpecialTileTrigger, which is a correctness bug
waiting to hit.

**Effort:** L. Requires a data migration on live data; the prefixed-string PKs are everywhere in
code and possibly logs / tests. Do it once, carefully.

**Risk:** Migration itself is the risk. In a fresh dev env it's trivial; on existing data it's a
proper table rewrite. Worth doing before the production cutover for the thesis.

**Thesis value:** High. "Native UUID vs prefixed-string PK: index sizes, query latency, ingest
throughput" is a very clean empirical chapter.

---

### Secondary (still ≥ 2 % individually or strong thesis value)

#### R6. Use `COPY FROM STDIN` in the flusher for `TurnEvent` and `SpecialTileTrigger`

Replace `TurnEvent.objects.bulk_create(all_turn_events)` and the trigger bulk_create with
`psycopg2.copy_expert("COPY turnevent (...) FROM STDIN WITH CSV", buf)`. Keep the Run `bulk_create`
as-is (batch is small — 50 runs).

Why: at ~1,000 turn rows per flush cycle, COPY is 3–5× faster than multi-row INSERT and produces
less WAL. Effort: M (needs care around JSON column formatting, NULL handling).
Risk: bypasses Django signals (none fire here anyway), and you lose `bulk_create(ignore_conflicts=)`
— but turns inside a successful run never conflict (the run-level dedup already handled that).
Thesis value: High. "Django bulk_create vs raw COPY" is gold for a DB chapter.

#### R7. Move validation out of the HTTP request, into the flusher

The heavy cross-field checks in `UnityIngestPayload._validate_moves_and_indices`
(`ingest_schemas.py:91-120`) and the canonical equivalent run on every request. Keep only field-level
validation on the HTTP path (`model_validate` with a lightweight schema); move the cross-field checks
to the flusher. Invalid payloads land in a `ingest_buffer_dead_letter` list with the error attached.

Why: less CPU on the hot HTTP path, and gives you a dead-letter pattern for free (R8). Effort: S.
Risk: buggy clients can no longer get a synchronous 400 for logic errors — only for schema errors.
That's acceptable because the game is fire-and-forget anyway (`202 Accepted`).
Thesis value: Moderate.

#### R8. Redis Streams + consumer groups instead of LIST

`XADD ingest_stream MAXLEN ~ 1000000 * <payload>` on the producer. Flushers use `XREADGROUP` with
consumer group `flushers`. Gives you: bounded backpressure via MAXLEN, parallel flushers, per-item
acknowledgement, automatic DLQ via pending-entries-list. Effort: M.
Risk: migration path — run LIST and Stream in parallel for a week.
Thesis value: Very high. "Redis LIST vs Streams for an ingest buffer" with throughput + latency
charts under identical hardware is a well-scoped thesis result.

#### R9. Declarative partitioning on `run`, `turnevent`, `specialtiletrigger` by week

Range-partition these tables by `run.created_at` (child tables partitioned by parent-week — use a
`created_at` column on `TurnEvent`/`SpecialTileTrigger` if needed, or partition on a derived
`week_start` that's set at insert). After the weekly rollup + archive, `DROP TABLE turnevent_w<N>`
is instant and doesn't touch the live write partition. Autovacuum runs per-partition (smaller,
faster). Effort: L.
Risk: existing `ON DELETE CASCADE` FKs + partitioning need care (PG 13+ supports FKs across
partitions). All queries must include the partition key.
Thesis value: Very high. This is the single most "textbook" postgres optimisation for
time-series-shaped data and maps cleanly onto the existing weekly-compaction model.

#### R10. Drop per-request INFO logs on the success path; log only errors + sampled successes

`_log_run_ingest_event(INFO, "run_ingest_queued", ...)` at line 163-168 of `ingest_router.py` fires
2,400 times/sec. Either drop it entirely or sample (`if random() < 0.001`). Same for
`run_ingest_duplicate` at line 122 if duplicates become common. Effort: S.
Risk: less visibility — counter with a metric (R11).

#### R11. Minimum-viable observability

Add a Prometheus client to the flusher and a statsd-style emitter to the HTTP handler. Minimum
metrics:
- `ingest_http_requests_total{status}`, `ingest_http_latency_seconds{quantile}`
- `ingest_buffer_depth` (`LLEN ingest_buffer` sampled every second)
- `flusher_batch_size` (observed — not just the config value), `flusher_batch_duration_seconds`,
  `flusher_flushed_total{model}`
- `flusher_dedup_rejections_total`, `flusher_batch_failures_total`

Effort: S. Thesis value: required as prerequisite for every other measurement.

#### R12. Tune `max_wal_size` and per-table autovacuum

Add to the postgres command in `docker-compose.prod.yml`:
```
-c max_wal_size=4GB
-c min_wal_size=1GB
```
And per-table: `ALTER TABLE turnevent SET (autovacuum_vacuum_scale_factor=0.05,
autovacuum_vacuum_insert_scale_factor=0.02, autovacuum_vacuum_cost_limit=2000);`. Same for
`specialtiletrigger` and `run`. Effort: S.

#### R13. Replace stdlib `json` with `orjson`

`json.loads(request.body)` in `ingest_router.py:69` and `json.loads(item)` in
`flush_ingest_buffer.py:70`. `orjson.loads` is 2–3× faster on payloads of this shape (nested lists +
dicts). Effort: S (add dep, two import swaps). Risk: none.

#### R14. Drop `game_map` from the payload + column (or dedupe by `map_version`)

Add a `GameMap(map_version PK, tiles JSONB)` table. Ingestion payload carries only `map_version`.
`Run.game_map` becomes unnecessary. Effort: M (needs coordination with Unity client for the
payload-shape change). Risk: clients on old versions must keep working during rollout.
Thesis value: High for the "payload size reduction" angle — measurable drop in ingest p95 and Redis
memory.

#### R15. Add a time-based flush trigger, not just size-based

Today the flusher runs a batch when `lrange` returns anything, then sleeps 100 ms if empty. That's
already time-bounded in practice, but under low load the batch is tiny (1–3 items). Either:
(a) add `min_batch_size=10, max_wait_ms=200` so under low load we still amortize COPY overhead, or
(b) accept small batches — given R6, COPY still wins for 10+ rows, and current behaviour is fine
for 1–3 rows. Effort: S. Thesis value: Low.

#### R16. Backpressure / dead-letter for the flusher

(a) Bound the Redis list with `LTRIM ingest_buffer 0 999999` occasionally from the flusher, or
(b) switch to Streams (R8). And: after N failed retries, move an item to `ingest_buffer_dlq`
instead of rpush-forever. Prevents poison pill stalls. Effort: S-M.

---

## 4. Things already done well

- **`synchronous_commit=off`** in prod PG config (`docker-compose.prod.yml:53`) — biggest
  commit-latency win, aligned with the 600 ms crash-loss tolerance.
- **PgBouncer in transaction pool mode** (`docker-compose.yml:55`) with matching Django settings
  (`CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True`, `settings.py:149-150`).
- **Redis write-buffer in front of Postgres** — the right architectural choice for this load shape.
- **Dedup in the flusher against the DB** (`flush_ingest_buffer.py:72-84`) — correct idempotency.
- **`bulk_create` under `transaction.atomic`** — one commit per batch, not per row.
- **Pipelined `LRANGE`+`LTRIM`** (`flush_ingest_buffer.py:61-64`) — atomic pop semantics without
  Lua.
- **Flusher as a separate process** with its own container (`docker-compose.yml:104-124`) — HTTP
  workers aren't stealing DB connections from the writer.
- **Failure recovery pushes the batch back to Redis** (`flush_ingest_buffer.py:201-207`) — correct
  direction (tail), preserves FIFO-ish ordering.
- **`Student.objects.filter(pk=...).exists()` not `.get()`** — cheapest possible existence check
  (will still go away under R1).

Don't undo these.

---

## 5. Explicitly not recommended

- **UNLOGGED staging table then move to logged.** Redis already plays the WAL-avoidance role for
  committed writes, and `synchronous_commit=off` gets the commit-latency win. UNLOGGED adds a
  second failure domain without a matching payoff.
- **Dropping FK constraints to `Student`/`Run`.** A FK to a PK over PgBouncer is sub-ms; the
  integrity is worth far more than the cost.
- **Switching payload to msgpack / protobuf at the HTTP layer.** Unity's WebGL client has good JSON
  tooling; binary framing saves maybe 20 % of parse time but costs significant implementation +
  debuggability. Only worth it if profiling shows JSON parse is > 10 % of handler time after R2,
  R13.
- **Moving to ClickHouse / Timescale.** Out of scope for 2 vCPU / 4 GB single-host thesis target.
  Postgres with partitioning (R9) gets you everywhere you need to be.
- **Uvloop + async redis without first doing R1.** R2 on its own (without dropping the two PG
  existence checks) only replaces one kind of blocking with another — you'd still serialise on the
  DB, just with a different error mode.
- **Micro-swaps of IntegerField → SmallIntegerField.** Per your ground rules: < 2 % win and not
  interesting for the thesis.

---

## 6. Measurement plan

### Baseline

Use the existing `benchmarks/docker-compose.benchmark.yml` stack — it already mirrors production
topology (PgBouncer, Redis, flusher). The dataset generator + k6 scripts are ready.

Before any change, capture a baseline for three scenarios:
- `benchmarks/scenarios/ingest_isolation.json` — pure write load, isolates the ingest path from
  dashboard contention.
- `benchmarks/scenarios/national_high.json` — closest to target peak.
- `benchmarks/scenarios/retry_storm_ingest.json` — catches the poison-pill / backpressure angle.

```bash
# From benchmarks/
python run_scenario.py ingest_isolation
python run_scenario.py national_high
python run_scenario.py retry_storm_ingest
```

### Metrics to capture (per run)

HTTP (from k6 output):
- `http_req_duration` p50 / p95 / p99
- `http_reqs` rate (sustained RPS actually achieved)
- Status distribution: 202 / 4xx / 5xx
- Record the `rate` k6 actually hit vs the requested rate — if k6 can't push the target load, the
  client is the bottleneck, not you.

Flusher (add via R11, or hand-roll via `logging.info` for the baseline):
- `LLEN ingest_buffer` sampled every 1 s — max, mean, tail. If this grows monotonically, the flusher
  is the bottleneck. If it stays near 0, it's the HTTP layer.
- Rows flushed per second (per model).
- Batch duration.
- Any batch failures.

Postgres:
- `pg_stat_statements` top 20 by total_time before/after, filtered to digitmileapi schema.
- `pg_stat_bgwriter.checkpoints_timed` vs `checkpoints_req` — the ratio tells you whether
  `max_wal_size` is too small (R12).
- `pg_stat_user_tables` for `run`, `turnevent`, `specialtiletrigger`: `n_tup_ins`, `n_live_tup`,
  `last_autovacuum`, `autovacuum_count`.
- `pg_stat_user_indexes` — confirm `idx_scan=0` for the indexes proposed for drop in R3.

System (2 vCPU / 4 GB is tight, make sure you're not hitting a host ceiling):
- `docker stats --no-stream` for each container — CPU %, mem, block I/O.
- `vmstat 1` inside the backend container during the run — look at `r` (runnable queue length) and
  `wa` (io-wait %).

### Bottleneck identification before implementing

From the code alone I can't tell whether R1+R2 or R3+R9 is the larger win — it depends on whether
the HTTP layer or PG write amplification is saturating first. The quickest discriminator:

1. Run `ingest_isolation` at target rate.
2. If `LLEN ingest_buffer` grows without bound → **flusher/PG is the bottleneck** → prioritise R6,
   R3, R12, R9.
3. If `LLEN ingest_buffer` stays small but HTTP p99 climbs and k6 can't hit the target rate →
   **HTTP layer is the bottleneck** → prioritise R1, R2, R4.

Given the 5-sync-worker cap and the two blocking DB calls per request, my prior is (3) — HTTP layer
first. But measure.

### Order of implementation (baseline → each change → rerun)

1. Baseline (all three scenarios).
2. R11 (observability) — prerequisite for every subsequent measurement.
3. R1 (drop `Run.exists`, cache `Student`) — smallest change, largest expected HTTP win.
4. R3 + R12 (index + autovacuum + `max_wal_size`) — cheap infra wins.
5. R2 + R4 (async + middleware trim) — the structural HTTP change.
6. R13, R7 (orjson + validation-in-flusher) — polish.
7. R6 (COPY) — flusher throughput chapter.
8. R8 + R16 (Streams + DLQ) — backpressure chapter.
9. R9 (partitioning) — final DB chapter.
10. R5, R14 (schema surgery) — last because they're the riskiest migrations.

Each step produces a clean before/after delta on the same three scenarios. That sequence is the
thesis outline.
