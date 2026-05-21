# Chapter: Architecture (§2.4–§2.7)

> Draft source document for the architecture portion of Chapter 2 of the thesis. This file is written in English as a working draft; the final thesis prose will be translated into Macedonian. Figure placeholders are marked `[Figure X]` and described at the end of this document.

---

## 2.4. High-level overview

The architecture of DigitMile is shaped by three simultaneous pressures established in §1.2 and §2.3: an ingest channel that must withstand national-scale load on limited hardware, a teacher dashboard that must remain responsive while that channel runs at full load, and a dataset that grows linearly with the duration of the school year. These three pressures cannot be satisfied at once by a single-tier architecture in which every ingest HTTP request writes directly to the relational database — the national-scale projection in §1.2 shows that such an approach would saturate the database CPU at levels of load substantially below the required capacity. Empirical confirmation of this saturation is presented in §5.

The system is therefore divided into three clearly separated containerized components that communicate through exactly three channel points. The Unity client, served as static WebGL resources by a dedicated nginx container, is an external input with no direct database access. The Django backend, served by gunicorn with five worker processes, handles every HTTP request — both from students (telemetry) and from teachers (dashboard). The flusher, a separate Python process that runs in the background, drains telemetry records from a Redis queue into PostgreSQL and incrementally updates the rollup tables. PostgreSQL and Redis serve as shared state stores between these components. The entire topology runs behind a reverse proxy (nginx) that handles SSL termination and path-based routing.

What makes this design distinctive is the separation of the write path from the read path. When the Unity client submits telemetry, Django validates the payload and writes it immediately into a Redis queue — without touching PostgreSQL. The request returns to the client in single-digit milliseconds. The flusher independently drains the queue in batches and performs the only write into PostgreSQL. The teacher dashboard, on the other hand, never reads from the raw telemetry tables — it reads only from the rollup tables, which are maintained as a materialized view of the aggregates. These two paths are depicted in [Figure 2].

**[Figure 2. Architectural topology: service boundaries and data paths]**

External systems (the outbound mail relay used for registration notifications, the CI/CD pipeline that deploys to the VPS, and monitoring tooling) are deliberately omitted from the diagram, as are the auxiliary Django management commands (`compact_weekly_runs`, `archive_week_replays`, `verify_weekly_rollups`) which run on demand or on schedule rather than as long-lived service loops. They are described in the relevant subsections of §2.7 and Chapter 3.

---

## 2.5. Architectural decisions and rationale

This subsection documents the principal design decisions that shape the system, together with the alternatives considered and the costs of each choice.

### 2.5.1. Asynchronous ingest channel via a Redis queue

The alternative — a synchronous HTTP path to PostgreSQL for every ingest request — was rejected on the basis of the national-scale projection: the expected load of approximately 11 RPS on a typical day, and up to roughly 29 RPS during "school bell" peaks, would saturate the database CPU on the target VPS, which in turn saturates the gunicorn worker pool and triggers cascading request drops. Instead, Django writes every validated request into the Redis queue via a single `LPUSH` operation — an operation with microsecond-scale latency — and immediately returns to the client. The flusher in the background drains records to PostgreSQL in batches.

The cost of this decision is the loss of strict "written-and-durably-stored" semantics. Records are held in Redis between acceptance and batch write, and could in principle be lost in the event of a catastrophic Redis failure during that interval. The acceptability of this cost rests on two facts: Redis is configured with AOF persistence (`appendonly yes`, `appendfsync everysec`), which bounds the loss window to under one second; and the pedagogical context does not require strict transactional guarantees per move — a single lost session represents a negligible loss of signal in the weekly aggregate.

### 2.5.2. Data tiering by temperature ("hot / warm / cold")

Data in the system is maintained in three distinct forms depending on age. Per-move raw records (tables `TurnEvent` and `LogTrigger`) are kept in "hot" form — indexed, directly writable — only for the current school week. At the end of the week, the weekly compaction pipeline (§2.7.2) collapses these records into two parallel forms: a "warm" form — fourteen rollup tables that contain the full informational signal needed by the teacher dashboard; and a "cold" form — one compressed JSON archive per session (model `ReplayArchive`), which preserves the complete sequence of moves required for session reconstruction under FR6. Once both forms are verified, the original hot rows are deleted.

This tiering resolves the tension between two opposing requirements: the dashboard requires fast aggregate reads, while FR6 requires faithful reproduction of every move, even for sessions from earlier in the school year. The two cannot be satisfied simultaneously over the same stored form — the first demands aggressive aggregation, the second demands complete preservation.

### 2.5.3. The dashboard reads only from rollup tables

As a direct consequence of §2.5.2, the read path of the teacher dashboard is designed never to access the hot tables. All visualizations and analytical views are fed exclusively by the rollup tables. The alternative would be a hybrid approach — historical aggregates from rollup tables, but "live" aggregates computed at request time from the current hot records. This alternative is explicitly rejected for two reasons. First, on-request computation introduces unpredictable latency (dependent on how many records have accumulated so far in the current week), which conflicts with NFR3. Second, the same aggregate computed from two different sources (rollup before compaction, hot rows after) can produce numerically different values, which undermines the teacher's trust in the displayed numbers.

The cost of this decision is that moves made by a student in the last few seconds are not immediately visible in the dashboard. This cost is mitigated by the incremental update of rollup tables inside the flusher (optimization H, §7.2): rollup tables are updated on every flush cycle rather than once per week, so the dashboard content is at most a few seconds stale.

### 2.5.4. Django-ninja for the ingest channel, DRF for the rest of the panel

The backend HTTP stack uses two different frameworks within the same Django project. The ingest channel (`/panel/api/runs/ingest/`) is implemented with Django-ninja and Pydantic v2 validation — a framework designed for high throughput and explicit schemas. The remaining endpoints of the teacher panel (classroom and student CRUD, registration, approval, session reconstruction) are implemented with classical DRF and Django views. The rationale is that the only high-RPS path is precisely the ingest path, and the cost of DRF serializers on it is measurable; for the rest of the low-RPS panel, the ergonomics and the integration of DRF with Django admin outweigh marginal performance gains.

### 2.5.5. Docker-compose, not Kubernetes

The platform is deployed as a group of containers orchestrated with docker-compose, not as a Kubernetes cluster. This decision follows directly from the target hardware (a single VPS with 2 vCPU / 3.8 GiB RAM, §1.2): a Kubernetes control plane would consume a substantial fraction of those resources without providing any functional benefit for a system that does not scale horizontally across nodes. Skeleton Kubernetes manifests exist in the project's `k8s/` directory as a starting point for future expansion, but are not part of the active deployment target.

---

## 2.6. Data model

The data model is split into four logical families, shown in [Figure 3]: the organizational hierarchy, the active (hot) gameplay entities, the aggregate (warm) rollup tables, and the archival (cold) entities.

**[Figure 3. ER diagram of the principal entities, colored by data temperature]**

### 2.6.1. Organizational hierarchy

The user base is modeled around four roles: the system administrator, the school, the teacher, and the student. Schools and teachers are linked through a dedicated junction entity that carries the status of their relationship (`PENDING`, `APPROVED`, `REJECTED`), allowing the same teacher to be associated with multiple schools in different states. A teacher owns `Classroom` records, and a classroom owns `Student` records. Isolation between schools (implicit in FR2) is enforced at the queryset-scoping level inside the views — a teacher never receives a queryset containing classrooms or students that do not belong to them. Students do not have their own credentials (see FR7); they are identified by an ID embedded in the payload submitted by the Unity game.

### 2.6.2. Gameplay entities (the hot set)

A single game session is represented by a `Run`, which carries metadata about it: the student, the level, the duration, the outcome, and the compaction status. Attached to each `Run` are several `TurnEvent` records — one per student move — and several `LogTrigger` records for special events (activation of tile number 3 or 5, entry into a special mode, and so on). These three tables form the "hot" set: they are written to intensively during the school week and read only by the background flusher and by the weekly compaction pipeline — never by the dashboard.

### 2.6.3. Aggregate entities (the warm set)

The fourteen rollup tables carry the pedagogical signal in a form designed for fast reads. They group into four families: per student (weekly performance, accuracy, decision time), per classroom (aggregates at the classroom level), per card type (performance per concept — `Move`, `Conditional`, `Loop`), and per level (performance by level complexity). Each rollup table has a clearly bounded cardinality of the form (student/classroom × week × level × card-type), which makes the rollup set predictably linear in growth: over one school year with approximately 60 000 students and 36 teaching weeks, the total order of magnitude of the rollup set stays in the millions of rows, rather than the billions of the hot set.

### 2.6.4. Archival entities (the cold set)

`ReplayArchive` is in a one-to-one relationship with `Run` and is created during weekly compaction. The payload is a compressed JSON document — a single object containing every move and triggered event of the session in playback order — stored under the filesystem path configured via `REPLAY_ARCHIVE_ROOT`. After the archive is written and rollup equivalence is verified, the original `TurnEvent` and `LogTrigger` rows for that session are deleted. The session reconstruction feature of FR6 loads these JSON documents and maps the moves on the client side for visual playback.

---

## 2.7. Data processing pipeline

The system runs two independent processing pipelines: a real-time channel through which telemetry is continuously received, validated, and stored; and a weekly background channel in which compaction and archiving are performed. Both pipelines operate over the same three stores (PostgreSQL, Redis, and the filesystem), but have entirely different performance profiles and safety mechanisms.

### 2.7.1. The real-time ingest channel

When the Unity client submits telemetry via a POST request to `/panel/api/runs/ingest/`, the sequence of steps is as follows. First, a gunicorn worker receives the request, performs a CSRF check, and forwards it to the Django-ninja router. Second, ninja validates the payload against a Pydantic schema that verifies all required fields and their types. Third, the validated payload is serialized as JSON and pushed into the Redis queue `ingest_buffer` via a single `LPUSH` operation. Fourth, the request returns to the client with an HTTP 202 response. The entire path is on the order of a few milliseconds (see §5.1).

In parallel, the flusher process runs a continuous loop: a blocking read from the same queue using `BRPOP` (or a batched variant), bulk decoding of the records that arrived, and a single PostgreSQL transaction that performs `bulk_create` of `Run`, `TurnEvent`, and `LogTrigger` rows. As part of the same transaction, the flusher incrementally updates the corresponding rollup tables — folding the new record into the weekly aggregates rather than recomputing the rollups from scratch. This incremental processing shifts the rollup tables from "recomputed once a week" to "always up to date", which closes the loop for NFR3.

### 2.7.2. The weekly compaction channel

Weekly, in the maintenance window (Friday 20:00 EET, when primary schools in North Macedonia generate no traffic), the management command `compact_weekly_runs` is executed. The command processes one school week of data at a time. First, it identifies all `Run` records from that week which are not yet compacted. Second, for each such run, it writes the compressed replay archive to disk (model `ReplayArchive`). Third, the command verifies numerical equivalence between the incrementally maintained rollup tables and the same rollups recomputed from scratch over the hot records (module `verify_weekly_rollups`) — this verification acts as a safety net against drift in the incremental path. Fourth, and only if all the previous steps have succeeded, the command deletes the original `TurnEvent` and `LogTrigger` rows for the processed week.

The weekly pipeline is designed to be idempotent and resumable on partial failure: the compaction status is held per `Run` record, so a re-run does not duplicate the operations. The duration of this compaction and its resource cost are measured and presented in §5.5.

---

## Figure descriptions (for the thesis author)

- **Figure 2 — Architectural topology.** Suggested elements: Unity WebGL client (left) sending HTTPS to nginx reverse proxy; nginx splitting traffic into two downstream services — the static-files nginx for the WebGL bundle and the gunicorn-served Django backend for the API and the teacher panel; Django writing into Redis (`ingest_buffer` queue) and reading from PostgreSQL (rollup tables only); flusher (separate process) reading from Redis and writing to PostgreSQL (hot tables and rollup tables); teacher browser (right) connecting to nginx and reaching the Django panel. Mark the *write* path and the *read* path in different visual styles (e.g., solid versus dashed arrows). The existing diagram in `docs/architecture.md` is outdated (no Redis queue, no flusher) and should not be used as-is.
- **Figure 3 — ER diagram colored by data temperature.** Suggested grouping: organizational hierarchy in neutral color; hot entities (`Run`, `TurnEvent`, `LogTrigger`) in a "warm" color (red/orange); rollup family in a "warm" color (yellow); archival entity (`ReplayArchive`) in a "cold" color (blue). Do not draw all fourteen rollup tables individually — represent the four families as four boxes labeled "per-student rollups", "per-classroom rollups", "per-card-type rollups", "per-level rollups".

## Editorial notes

- All section numbers used in cross-references (§1.2, §2.3, §5, §5.1, §5.5, §7.2) assume the chapter structure declared in §1.4 of the existing thesis PDF. Adjust if numbering changes during writing.
- Forward references to Chapter 5 deliberately do not quote measured values — claims live here, evidence lives there.
- This draft is approximately 5 pages at typical thesis density. Cuttable sections, in priority order if the page budget tightens: §2.5.4 (ninja/DRF split), §2.5.5 (docker-compose vs Kubernetes), then trim §2.6.3 (rollup family description) to a single paragraph.
- Items deliberately *not* covered here, because they belong to Chapter 3 (Implementation): CSRF and CORS configuration; specific cache TTLs and Redis configuration values; deployment topology details (Docker images, environment variables, CI/CD); the PgBouncer history (which is now empirical evidence, not design rationale, and lives in Chapter 5).
