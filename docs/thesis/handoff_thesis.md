# Codex Handoff: Thesis–Repository Alignment for DigitMile

## Purpose

You are working inside the DigitMile repository. Your task is to explore the repository and help strengthen the thesis text by grounding architectural, implementation, and validation claims in the actual codebase.

The thesis is not asking for generic wording. It needs technically accurate academic framing that matches the real implementation.

The main focus is the architecture and implementation of a scalable web platform for analytics of an educational Unity game. The thesis argues that DigitMile transforms detailed move-level game telemetry into pedagogically relevant analytics for teachers, while remaining usable on limited server infrastructure.

## Expected input files

Look for the thesis files in the repository, likely under one of these paths:

```text
/docs/thesis/thesis_current.md
/docs/thesis/diplomska-current.pdf
/docs/thesis/handoff.md
```

If both Markdown and PDF versions exist, use the Markdown file as the primary text source. Use the PDF only as a layout/visual reference if needed. The Markdown conversion may have lost some formatting, so do not over-focus on formatting problems unless they affect meaning.

## Communication language

When giving thesis wording, corrections, replacement paragraphs, or Macedonian academic formulations, write those formulations in Macedonian.

For all explanations, repository findings, technical reasoning, and implementation summaries, English is preferred.

## High-level thesis context

DigitMile is a web platform built around an existing Unity educational game. The game is intended for pupils in grades 4–6 and teaches computational/programming thinking concepts through card-based gameplay.

The platform adds:

- telemetry collection from Unity game sessions;
- backend validation and ingestion;
- buffering through Redis;
- asynchronous/batched persistence into PostgreSQL;
- teacher dashboard analytics;
- weekly aggregation/compaction;
- replay archival for historical session reconstruction;
- Dockerized deployment;
- CI/CD and production infrastructure;
- load testing with k6.

The thesis frames the central problem as follows:

```text
The main challenge is not merely storing game results, but transforming high-frequency, move-level telemetry into pedagogically meaningful analytics under limited infrastructure constraints.
```

The architecture is currently framed around three principles:

1. separating telemetry ingestion from durable persistence;
2. separating raw telemetry from analytical read models;
3. periodically compacting detailed telemetry into long-term aggregate representations.

When reviewing or improving thesis text, preserve this framing unless the repository contradicts it.

## Main repository areas to inspect

Please explore the repository and identify the actual implementation of the following components.

### 1. Telemetry ingestion endpoint

Find the endpoint where the Unity client submits completed game/session telemetry.

Likely clues:

- Django
- Django Ninja
- Pydantic schemas
- endpoint names related to telemetry, ingest, run, session, game, analytics, submit
- HTTP API route used by Unity/WebGL

For this part, determine:

- exact route/path;
- HTTP method;
- authentication/identification mechanism;
- request payload structure;
- whether validation is done with Pydantic v2;
- whether the endpoint writes directly to PostgreSQL or only enqueues into Redis;
- what response is returned to the client;
- whether any lightweight counters/statistics are updated synchronously.

The thesis currently claims that the ingest endpoint performs validation and queues the payload into Redis, while durable PostgreSQL persistence is delegated to a background Flusher service. Verify this.

### 2. Pydantic schema / telemetry payload model

Find the schema/model used to validate telemetry payloads.

Determine:

- schema class names;
- major payload fields;
- whether the payload is session-level, turn-level, event-level, or mixed;
- how player/student identity is represented;
- how level, card choice, offered cards, decision time, correctness, special fields, and replay reconstruction data are represented;
- whether the schema supports full reconstruction of a game session;
- whether validation is strict enough to justify the thesis wording.

The thesis should not overclaim. If some metrics are not present in the code, point that out.

### 3. Redis queue/buffer

Find where Redis is used for ingest buffering.

Determine:

- Redis client/library;
- queue/list/stream/key name, for example `ingest_buffer`;
- whether the implementation uses Redis lists, streams, pub/sub, or another pattern;
- whether data is serialized as JSON, compressed JSON, msgpack, etc.;
- whether Redis persistence is configured through AOF/RDB;
- what failure mode exists if Redis crashes before flushing;
- whether retries or dead-letter handling exist.

This matters because the thesis discusses Redis as both a cache and a write buffer. Check whether both uses are actually implemented.

### 4. Flusher/background persistence service

Find the background service that drains Redis and writes to PostgreSQL.

Likely clues:

- file/class/function names containing `flusher`, `worker`, `ingest`, `flush`, `buffer`, `queue`, `batch`
- Django management command
- standalone Python process
- Docker Compose service

Determine:

- how it is launched;
- whether it is a separate container/process;
- how frequently it polls Redis;
- batch size;
- transaction boundaries;
- whether writes are bulk inserts or ORM loops;
- which tables it writes to;
- how failures are handled;
- whether partially failed batches can duplicate or lose records;
- whether idempotency exists;
- whether it updates any aggregate/statistics tables during ingestion.

The thesis currently claims that the Flusher drains Redis in batches and writes to PostgreSQL, reducing synchronous work in the HTTP request path. Confirm the exact mechanics.

### 5. Raw telemetry database models

Find Django models for raw telemetry.

Likely names from the thesis:

- `Run`
- `TurnEvent`
- `LogTrigger`

Determine:

- exact model names;
- fields;
- relationships;
- indexes;
- whether they are considered “hot”/active tables;
- how long data remains there before compaction;
- whether raw data is enough to reconstruct sessions.

Use this to improve the thesis section on raw telemetry, active tables, and replay reconstruction.

### 6. Aggregation/statistics tables

Find models/tables used for analytics shown in the teacher dashboard.

The thesis claims there are fourteen statistical/aggregate tables. Verify:

- exact number;
- exact model/table names;
- what each table aggregates;
- dimensions used: week, pupil, class, level, card type, correctness, decision time, etc.;
- whether they are updated incrementally during flushing, weekly during compaction, or both;
- indexes used for dashboard queries;
- whether Redis caching is used for these views.

If the repository does not support the “fourteen tables” claim, flag it.

### 7. Weekly compaction and replay archival

Find the code responsible for weekly aggregation/compaction.

Likely clues:

- management commands
- cron scripts
- Celery/worker tasks if any
- Docker Compose scheduled jobs
- names like `aggregate`, `compact`, `archive`, `rollup`, `weekly`

Determine:

- trigger mechanism;
- whether it runs weekly;
- whether it archives replay data;
- archive format: compressed JSON, gzip, JSONField, file storage, database blob, etc.;
- whether raw rows are deleted after archive/aggregation;
- whether the teacher dashboard can still reconstruct old sessions;
- how cache invalidation is synchronized with aggregation.

The thesis claims that raw detailed telemetry is compacted into aggregate tables, replay data is archived as compressed JSON, and raw detailed rows are removed from active tables while preserving historical replay functionality. Verify this carefully.

### 8. Teacher dashboard read path

Find views/API endpoints/templates powering the teacher dashboard analytics.

Determine:

- whether dashboard reads raw telemetry, aggregate tables, Redis cache, or a combination;
- what charts/statistics are shown;
- whether access control ensures teachers only see their own classes/pupils;
- whether dashboard queries are optimized/indexed;
- whether Redis cache invalidation exists;
- whether dashboard remains independent of the ingest write path.

This is important for the thesis claim that reads and writes are separated.

### 9. Authentication, authorization, schools, teachers, pupils

Find models and flows for:

- school registration;
- teacher registration;
- approval/rejection;
- pupil creation;
- class management;
- teacher authorization;
- pupil/student identifiers used by Unity.

Verify thesis functional requirements:

- teachers can manage only their own classes/pupils;
- admins approve/reject schools/teachers;
- rejecting does not delete associated data;
- pupils use school-issued identifiers rather than complex passwords;
- multilingual UI exists for Macedonian, Albanian, and English.

### 10. Docker and infrastructure

Inspect deployment files:

- `docker-compose.yml`
- production compose files
- Dockerfiles
- NGINX configs
- Gunicorn config
- PgBouncer config
- Redis config
- GitHub Actions workflows
- Certbot/Let's Encrypt scripts

Determine:

- exact service list;
- whether Unity WebGL is served from a separate NGINX/static container;
- whether reverse proxy handles SSL termination and path routing;
- whether Django runs behind Gunicorn;
- number of Gunicorn workers if configured;
- whether PgBouncer is used and how;
- whether Redis is used for cache, queue, or both;
- whether CI/CD builds Docker images and deploys over SSH;
- whether Let's Encrypt is automated.

The thesis should not claim services/configuration that are not present.

### 11. k6 load testing and validation

Find load testing scripts and reports.

Likely clues:

- `k6`
- `load-test`
- `performance`
- `stress`
- `ingest`
- `reports`
- Dockerized testing environment

Determine:

- tested scenarios;
- sustained RPS;
- peak RPS;
- teacher dashboard tests during ingest load;
- overload recovery tests;
- aggregation/compaction tests under load;
- hardware assumptions;
- p95 latency results;
- error rates;
- Redis queue drain time;
- CPU/RAM measurements if available.

The thesis currently defines NFR thresholds such as:

- sustained ingest: at least 11 RPS for 15 minutes;
- p95 HTTP latency under 1000 ms;
- fewer than 0.5% rejected requests;
- peak/bell scenario: 23 RPS for 60 seconds, no HTTP 5xx, Redis drain within 30 seconds;
- dashboard p95 under 3000 ms during 11 RPS ingest;
- overload recovery after 22 RPS;
- target hardware around 2 vCPU and 3.8 GiB RAM.

Verify whether tests actually support these claims.

## What to produce after exploration

Please produce a concise repository-grounded report with the following sections.

### A. Verified architecture facts

List what the repository confirms.

Example format:

```markdown
- The telemetry ingest endpoint is implemented in `path/to/file.py` as `function_name`, exposed at `POST /api/...`.
- It validates the payload using `SchemaName` from `path/to/schema.py`.
- It enqueues payloads into Redis key `...` using `...`.
- PostgreSQL writes are performed by `...` in `path/to/flusher.py`.
```

Include file paths and function/class names.

### B. Claims that need correction or softer wording

List any thesis claims that are not fully supported by the repository.

Examples:

```markdown
- Thesis says Redis is configured to limit data-loss window, but no Redis AOF/RDB persistence config was found.
- Thesis says there are fourteen aggregation tables, but only twelve aggregate models were found.
- Thesis says the dashboard never reads raw telemetry, but `dashboard/views.py` directly queries `TurnEvent` for X.
```

### C. Recommended Macedonian wording

Provide replacement paragraphs or sentence-level corrections in Macedonian.

Focus especially on sections:

- 2.4 High-level architecture overview;
- 2.5.1 Asynchronous ingestion channel;
- 2.5.2 Redis as cache and queue;
- 2.5.3 Batch writes;
- 2.5.4 Precomputed aggregate tables;
- 2.5.5 Weekly compaction and session archival;
- 2.5.6 Dockerized multi-container deployment;
- optional PgBouncer section if implemented.

### D. Missing technical details worth adding to the thesis

Suggest repository-grounded details that would make the thesis stronger, for example:

- exact queue name;
- exact batch size;
- exact aggregate table names;
- indexes;
- transaction strategy;
- cache invalidation logic;
- Docker services;
- k6 scenario names and results.

### E. Suggested thesis outline for the next chapter

If implementation details are clear, suggest how Chapter 3 should be organized.

Possible structure:

```text
3. Implementation
3.1 Unity telemetry generation
3.2 Telemetry payload schema and validation
3.3 Ingest endpoint implementation
3.4 Redis buffering and Flusher service
3.5 PostgreSQL data model
3.6 Aggregation and compaction pipeline
3.7 Teacher dashboard implementation
3.8 Docker deployment and CI/CD
```

Adjust this based on the repository.

## Important writing guidance

Use precise academic language. Avoid overclaiming.

Prefer:

```text
Овој дизајн ја намалува количината на синхрона работа во HTTP барањето...
```

over:

```text
Овој дизајн гарантира многу брз одговор...
```

Prefer:

```text
потенцијална загуба на мал број записи во исклучителни отказни сценарија
```

over:

```text
една загубена сесија не е битна
```

Prefer:

```text
претходно пресметани агрегациски табели
```

over:

```text
материјализиран view
```

unless actual PostgreSQL materialized views are used.

Prefer:

```text
трајно складирање
```

over:

```text
перзистирање
```

unless the surrounding text consistently uses the technical term.

Prefer:

```text
редицата
```

over:

```text
queue-то
```

Prefer:

```text
пакетно запишување
```

over:

```text
batch-ови
```

Prefer:

```text
краткотрајни пикови на сообраќај
```

over:

```text
bursty traffic
```

## Known current wording issues in the thesis

The current thesis text contains some wording that should likely be improved:

```text
опфажа сржта
```

Replace with something like:

```text
ја опфаќа суштината
```

or restructure the sentence.

```text
значителни и информативни педагошки аналитики
```

Prefer:

```text
педагошки релевантни аналитички увиди
```

```text
одненадежен високо волуменски сообраќај
```

Prefer:

```text
ненадеен сообраќај со висок волумен
```

```text
допринесува
```

Prefer:

```text
придонесува
```

```text
во предвид
```

Prefer:

```text
предвид
```

```text
оддржување
```

Prefer:

```text
одржување
```

```text
константо
```

Prefer:

```text
постојано
```

```text
долготрајно складирањето
```

Prefer:

```text
долготрајното складирање
```

```text
SQL кверињата
```

Prefer:

```text
SQL пребарувањата
```

or, if technical tone is preferred:

```text
SQL барањата
```

## Suggested Macedonian replacement for Section 2.5 opening

Use this if it matches the repository:

```text
Архитектонските одлуки во DigitMile произлегуваат од еден централен предизвик: трансформација на високофреквентна и детална телеметрија во педагошки релевантни аналитички увиди, во услови на ограничена инфраструктура. Овој предизвик е адресиран преку три основни принципи: одвојување на внесот на податоци од нивното трајно складирање, одвојување на сировата телеметрија од аналитичките модели што се користат за приказ во наставничкиот панел, и периодично компактирање на деталните записи во долгорочни агрегирани претстави. Секој од овие принципи решава различен потпроблем, а заедно овозможуваат системот да остане одзивен, скалабилен и одржлив во текот на целата учебна година.
```

## Suggested Macedonian replacement for Redis trade-off paragraph

Use this only if the repository actually uses Redis as a queue/buffer:

```text
Оваа одлука воведува компромис меѓу едноставноста, перформансите и гаранциите за трајност. Бидејќи Redis во оваа архитектура се користи како бафер меѓу клиентскиот сообраќај и PostgreSQL, податоците што моментално се наоѓаат во редицата можат да бидат изложени на ризик при отказ на Redis сервисот, зависно од неговата конфигурација. Во рамките на овој труд, овој компромис се смета за прифатлив поради две причини: прво, со соодветна Redis конфигурација може значително да се намали временскиот прозорец во кој е можна загуба; второ, аналитичката вредност на системот се темели главно на агрегирани неделни показатели, каде потенцијална загуба на мал број записи во исклучителни отказни сценарија би имала ограничено влијание врз целокупниот сигнал.
```

## Suggested Macedonian PgBouncer section

Use this only if PgBouncer is actually implemented:

```text
Бидејќи системот користи повеќе процеси кои можат паралелно да комуницираат со PostgreSQL — Django worker процеси, Flusher сервисот и административните операции — директното отворање голем број конекции кон базата може да создаде непотребен притисок врз PostgreSQL. За таа цел се користи PgBouncer како connection pooler. PgBouncer овозможува повторна употреба на постоечки конекции и го намалува трошокот за нивно отворање и затворање, што е особено важно во ограничена VPS околина. Оваа одлука ја поддржува целта системот да остане стабилен при комбинирано оптоварување од ingest каналот и наставничкиот контролен панел.
```

## Do not do this

Do not invent implementation details.

Do not assume the thesis is correct if the repository says otherwise.

Do not rewrite the entire thesis unless specifically asked.

Do not focus only on grammar; the primary goal is repository-grounded thesis strengthening.

Do not use vague phrases like “the system is scalable” without tying them to code, tests, or explicit NFRs.

Do not suggest adding technologies that are not already in the project unless clearly separated as optional future work.

## Final objective

After repository exploration, help convert the architecture and implementation chapters into a defensible engineering thesis:

```text
requirements → architectural pressure → design decision → implementation evidence → validation result
```

Every major claim should be traceable either to repository code, configuration, tests, or measured results.
