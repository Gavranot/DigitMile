# Benchmark compose overlays

Each overlay reverts one of the in-tree architectural optimizations to its
pre-optimization state so the benchmark suite can produce before/after deltas
on identical hardware. Overlays only ever touch the benchmark stack — they are
applied via `run_scenario.py` when a scenario JSON lists them under
`compose_overlays`, and the production compose files never reference them.

| Overlay | Optimization reverted | Mechanism |
|---|---|---|
| `no-pgbouncer.yml` | A — PgBouncer + Django pool settings | Replaces pgbouncer with a no-op busybox; flips backend/flusher to `benchmark-db` directly with `CONN_MAX_AGE=60`, server-side cursors re-enabled |
| `pg-defaults.yml` | B — PostgreSQL tuning | Replaces the `-c synchronous_commit=off …` command with a bare `postgres` |
| `dummy-cache.yml` | D — django-redis query cache | Sets `DJANGO_CACHE_BACKEND=dummy` on backend + flusher |
| `no-flusher.yml` | (companion to baseline images) | Replaces the flusher with a sleeping busybox. Required when the `benchmark_image_ref` is older than `e27b758` (the commit that introduced `flush_ingest_buffer`). |

Optimizations C (rollup-only analytics), E (django-ninja + Pydantic ingest),
and F (Redis write-buffer) are not reversible via overlay because the
predecessor code was deleted when those changes shipped. Use the baseline
git tags instead — see "Optimization toggles" in `benchmarks/README.md`.
For F (and any older baseline) pair the `benchmark_image_ref` with the
`no-flusher.yml` overlay so the flusher container doesn't crash-loop on a
management command that doesn't exist yet at that commit.

## Combining overlays

Overlays compose. A scenario can list multiple and they merge left-to-right:

```json
"compose_overlays": ["no-pgbouncer.yml", "pg-defaults.yml"]
```

This would model "what does the ingest endpoint look like before *any* infra
tuning landed" — useful as a single all-defaults baseline run.
