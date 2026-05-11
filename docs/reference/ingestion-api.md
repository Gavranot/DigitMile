# Backend Ingestion and API Surface

Last updated: 2026-03-09

## Why this subsystem exists

The API layer connects the Unity game, teacher-facing browser features, and admin workflows to the database. It also acts as the normalization boundary where Unity payload quirks are converted into stable backend records.

## Route layout

Root routing is defined in `DigitMilePanel/digitmile/urls.py`.

- HTML/admin routes live under `/panel/`
- API routes live under `/panel/api/`

## Endpoint inventory

### Public and gameplay-facing endpoints

| Path | Method | Consumer | Auth | Primary effect |
| --- | --- | --- | --- | --- |
| `/panel/api/fetchCSRFToken/` | `GET` | Unity/browser | allow any | returns CSRF token |
| `/panel/api/checkStudentCredentials/` | `POST` | Unity | anonymous throttle | validates student by name + DOB |
| `/panel/api/checkClassroomKey/` | `POST` | Unity | anonymous throttle | resolves classroom, teacher name, and students |
| `/panel/api/insertLevelStatistics/` | `POST` | Unity legacy | anonymous throttle | writes `RunStatistics` |
| `/panel/api/runs/ingest/` | `POST` | Unity | anonymous throttle | idempotent run ingestion via Redis buffer |

### Teacher/admin JSON endpoints

| Path | Method | Consumer | Auth | Primary effect |
| --- | --- | --- | --- | --- |
| `/panel/api/teacher/students/` | CRUD | teacher UI/API | `IsTeacher` | manage students in teacher-owned classrooms |
| `/panel/api/teacher/classrooms/` | `GET` | teacher UI/API | `IsTeacher` | list teacher classrooms |
| `/panel/api/teacher/school/` | `GET` | teacher UI/API | `IsTeacher` | list assigned schools except rejected |
| `/panel/api/teacher/run-statistics/` | `GET` | teacher UI/API | `IsTeacher` | list legacy `RunStatistics` rows |
| `/panel/teacher/statistics/viz-data/` | `GET` | teacher dashboard JS | login + teacher status | returns lazy chart payloads |

### Registration and admin workflow routes

| Path | Method | Purpose |
| --- | --- | --- |
| `/panel/` | `GET`, `POST` | teacher login landing page |
| `/panel/register/school/` | `GET`, `POST` | school registration form |
| `/panel/register/teacher/` | `GET`, `POST` | teacher registration form |
| `/panel/registration-success/` | `GET` | post-registration confirmation |
| `/panel/api/pending-registrations/` | `GET` | superuser review page |
| `/panel/api/approve-school/<id>/` | `GET` | approve pending school |
| `/panel/api/reject-school/<id>/` | `GET` | reject pending school |
| `/panel/api/approve-teacher/<id>/` | `GET` | approve pending teacher |
| `/panel/api/reject-teacher/<id>/` | `GET` | reject pending teacher |
| `/panel/teacher/statistics/` | `GET` | teacher dashboard page |
| `/panel/teacher/runs/<run_id>/` | `GET` | run replay page |

## CSRF and session flow

### Why it exists

Unity is expected to use Django's CSRF protection while calling session-authenticated endpoints.

### Current behavior

- `FetchCSRFTokenView` uses `UnsafeSessionAuthentication`, which disables CSRF enforcement only for the token-fetch endpoint.
- The endpoint returns `{"csrfToken": "..."}`.
- Repository instructions in `AGENTS.md` state that Unity fetches this token from `/panel/api/fetchCSRFToken/` and then sends it in the `X-CSRFToken` header.

### Operational note

- Most API views rely on DRF defaults because there is no explicit `REST_FRAMEWORK` setting block.

## Student bootstrap flow from the Unity client

### 1. Classroom lookup

`CheckClassroomKeyView`:

- accepts `classroomKey`
- looks up `Classroom` by `classroom_key`
- returns:
  - serialized school info
  - teacher name as a plain string
  - list of students as `{studentName, studentID}` objects

Important details:

- It does not enforce school/teacher status checks.
- It uses `print()` and broad exception handling instead of structured logging.

### 2. Student credential verification

`CheckStudentCredentialsView`:

- accepts `studentName` and `studentBirthDate`
- parses either `YYYY/MM/DD` or `YYYY-MM-DD`
- does a global `Student.objects.get(full_name=..., date_of_birth=...)`
- returns student identity and classroom info on success

Important edge cases:

- Missing fields -> `400`
- invalid date format -> `400`
- not found -> `404`
- multiple matches -> `409`

Important trust limitation:

- The lookup is not classroom-scoped, so duplicate name/DOB across classrooms is a real ambiguity path.

## Legacy ingestion: `insertLevelStatistics/`

### Why it exists

This is the older coarse-grained ingestion path. It stores one summary row per gameplay attempt without turn-level detail.

### Input contract

- `classroomKey`
- `user` (student full name)
- `levelStatistics` dict

Validation:

- serializer only requires that `levelStatistics.place` exists and is an integer
- the view then resolves the student by `classroomKey + full_name`

Write behavior:

- creates one `RunStatistics` row
- computes `player_won` as `place == 1`

Failure behavior:

- classroom not found -> `404`
- student not found in that classroom -> `404`
- unexpected error -> `500`

## Unity ingestion: `runs/ingest/`

### Why it exists

The single full-fidelity ingestion path. Accepts a Unity-shaped payload, validates it with pydantic-core (`ingest_schemas.py`), pushes the normalized canonical form to a Redis buffer, and returns `202` synchronously. A separate flusher worker (`flush_ingest_buffer` management command) drains the buffer into Postgres in batched transactions, writing `Run` + `TurnEvent` + `SpecialTileTrigger` rows.

The legacy DRF `insertRunData/` endpoint was removed on 2026-05-11 after the Unity client migrated to this endpoint.

### Input contract

Validated by `UnityIngestPayload` (in `ingest_schemas.py`). Same payload shape Unity has always sent — no client-side changes required beyond the URL.

Top-level payload:

- `classroomKey`, `user`, `userID`, `run`

Nested run payload:

- `level`, `score`, `place`, `correct_moves`, `wrong_moves`
- `runStartedUnixMs`, `runEndedUnixMs`
- `gameMap.mapTiles`, `turns[]`

Nested turn payload:

- `turnIndex`, `timestampPlayedUnixMs`
- `chosenCard`, `offeredCards`, `wasCorrect`
- `playerPositionBefore`, `playerPositionAfter`
- `botPositionsBefore`, `botPositionsAfter`, `tileBefore`
- `cardDecisionTimeMs`
- optional number-choice fields and `specialTileTriggers`

Gameplay meaning:

- `wasCorrect` means the player selected the correct destination tile for the movement implied by the chosen card
- number choice appears in levels 5 and 6; the chosen number becomes the next turn's bag number

### Validation rules

- `userID` must refer to an existing `Student`
- turn indices must be sequential from `0`
- chain indices within each turn must be sequential from `0`
- `wrong_moves` must match count of `wasCorrect == false`
- `correct_moves` must match turn-level correct count, except the validator subtracts `1` when `place == 1` because Unity "counts the last turn"
- `chosenNumber == -1` and `numberDecisionTimeMs == -1` are sentinel values normalized to `None`

### Normalization before write

`normalize_unity_run_ingestion_payload` (in `run_ingestion.py`) flattens the Unity shape into canonical snake_case before the payload hits Redis. Card normalization (`_normalize_cards_for_ingestion`, `_extract_card_metadata` in `views.py`) runs in the flusher worker at write time:

- `Bug`, `Back`, `AllBack*` card types normalize to `Back`
- `MoveX`/`Back` cards with missing `thenValue` get `thenValue=1` injected
- card metadata is extracted into `chosen_card_type`, `chosen_card_family`, `chosen_card_tile_type`

### Persistence flow

Two-stage:

1. **Endpoint** (`ingest_router.py` `ingest_run`):
   - parse + validate Unity payload (Rust JSON parse via `TypeAdapter.validate_json`)
   - check `Run.id` idempotency against Postgres → return `200` if already exists
   - check recording-window status against `runEndedUnixMs` → return `409` if closed
   - `LPUSH` validated canonical payload to `settings.INGEST_BUFFER_REDIS_KEY`
   - return `202`

2. **Flusher worker** (`python manage.py flush_ingest_buffer`):
   - pops up to `INGEST_BUFFER_BATCH_SIZE` items per iteration via `LRANGE + LTRIM` pipeline
   - dedupes within batch and against existing `Run.id`s in Postgres
   - bulk-creates `Run`, then `TurnEvent`, then `SpecialTileTrigger` in one transaction
   - on failure, returns items to the queue tail for retry

The flusher is a hard runtime dependency. If it isn't running, runs queue indefinitely in Redis without persisting.

### Data mapping details that matter

- `Run.id` is deterministic: `run_<sha256_32>` derived from canonical Unity fields via `derive_run_id_from_unity_payload`. Same payload twice → same `run_id` → idempotent retries.
- `player_won` is derived as `place == 1`
- `elapsed_ms = clamp_elapsed_ms(runStartedUnixMs, runEndedUnixMs)`: clamped to `[0, 7_200_000]`
- `game_map` stores `gameMap.mapTiles`
- `tile_before_type` uses Unity's `tileBefore.tileIndex`, not `tileType`
- `special_tile_type` uses `specialTile.tileIndex`
- `target_tile_type` is hard-coded to `0` because the Unity payload doesn't include it
- canon: clown trigger is `-4`, skateboard is `+5`

### Trust boundary

`runs/ingest/` ignores `classroomKey` and `user` after validation. The only enforced student identity is `userID`. The server trusts the client not to mismatch these fields.

### Response behavior

| Condition | Status | Body |
| --- | --- | --- |
| accepted (queued) | `202` | `{"message": "Run accepted", "run_id": "..."}` |
| duplicate (already persisted) | `200` | `{"message": "Run already ingested", "run_id": "..."}` |
| validation failure | `400` | `{"error": "Validation failed", "details": [...]}` |
| malformed JSON | `400` | `{"error": "Invalid JSON"}` |
| closed recording week | `409` | `{"error": "Statistics recording for this week is closed...", "week_start": "...", "recording_closed_at": "..."}` |

A `202` response does **not** guarantee the row is in Postgres yet — only that the payload is in the Redis buffer. The flusher typically writes within ~50ms but a downstream consumer querying the DB immediately may not see the row.

## Teacher-scoped CRUD/API endpoints

### `TeacherStudentViewSet`

- permission class: `IsTeacher`
- queryset: students whose classroom belongs to the authenticated teacher
- serializer filters `classroom_id` choices to the teacher's classrooms
- teachers can create, update, and delete only within their own classroom scope

### `TeacherClassroomListView`

- lists classrooms owned by the authenticated teacher

### `TeacherSchoolView`

- returns all assigned schools except rejected ones
- includes both `PENDING` and `APPROVED` schools by design

### `TeacherRunStatisticsListView`

- lists legacy `RunStatistics` rows for students in the teacher's classrooms

## Teacher statistics and replay routes

### `/panel/teacher/statistics/`

- server-renders dashboard shell plus summary data
- supports `grade` and `classroom` query filters

### `/panel/teacher/statistics/viz-data/`

- requires `section=analytics` or `section=turn_insights`
- caches per teacher/filter combination for 5 minutes
- returns JSON payload consumed by Chart.js in the template

### `/panel/teacher/runs/<run_id>/`

- superusers can replay any run
- teachers can replay only runs for their own students
- bundles run, turns, and grouped triggers into `run_data_json` for client-side replay rendering

## HTML templates and how views populate them

### `home.html`

- populated only with Django messages
- POST login handled inline in `home_view`

### `register_school.html`

- receives `form` and `google_maps_api_key`
- JavaScript fills hidden `latitude`, `longitude`, and `google_maps_address`

### `register_teacher.html`

- receives `form`
- iterates `form.schools.field.queryset`
- front-end JS manages 1-to-3 school selection and reveals `years_at_school_<school_id>` inputs

### `pending_registrations.html`

- receives pending school and teacher lists with "similar email" warnings

### `teacher_statistics.html`

- receives summary arrays as JSON blobs:
  - `student_data_json`
  - `comparison_student_data_json`
  - `classroom_stats_json`
  - `comparison_classroom_stats_json`
  - `starter_viz_data_json`

### `teacher_run_replay.html`

- receives `run_data_json`
- all replay logic, card explanation, bag-number reconstruction, and map highlighting happen in template JavaScript rather than the server view

## Operational guidance

- If you change Unity payload shape, update both the serializer and the matching write path.
- If you change stored card payloads, update normalization helpers in both `views.py` and `analytics.py`.
- If replay looks wrong, compare `game_map`, `tile_before_type`, and trigger `target_tile_type` against what Unity actually sends.

## Open questions / uncertainty notes

- The backend infers several gameplay concepts from Unity payload structure, but does not itself define the canonical game rules.
- The exact reason Unity's win path requires `correct_moves - 1` to match turn data is only explained by a code comment, not by a formal contract in this repository.
