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
| `/panel/api/insertRunData/` | `POST` | Unity current | anonymous throttle | writes `Run`, `TurnEvent`, `SpecialTileTrigger` |
| `/panel/api/runs/ingest/` | `POST` | non-Unity/internal style client | anonymous throttle | idempotent run ingestion |

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

## Current Unity ingestion: `insertRunData/`

### Why it exists

This is the main full-fidelity Unity ingestion path. It persists a run, every turn in that run, and any chained special-tile triggers.

### Input contract

Validated by `UnityRunUploadPayloadSerializer`.

Top-level payload:

- `classroomKey`
- `user`
- `userID`
- `run`

Nested run payload includes:

- `level`, `score`, `place`, `correct_moves`, `wrong_moves`
- `runStartedUnixMs`, `runEndedUnixMs`
- `gameMap.mapTiles`
- `turns[]`

Nested turn payload includes:

- `turnIndex`, `timestampPlayedUnixMs`
- `chosenCard`, `offeredCards`
- `wasCorrect`
- `playerPositionBefore`, `playerPositionAfter`
- `botPositionsBefore`, `botPositionsAfter`
- `tileBefore`
- `cardDecisionTimeMs`
- optional number-choice fields and `specialTileTriggers`

Gameplay meaning clarified by you:

- `wasCorrect` means the player selected the correct destination tile for the movement implied by the chosen card
- number choice appears in levels 5 and 6, and the chosen number becomes the next turn's bag number

### Validation rules

- `userID` must refer to an existing `Student`
- turn indices must be sequential from `0`
- chain indices within each turn must be sequential from `0`
- `wrong_moves` must match count of `wasCorrect == false`
- `correct_moves` must match turn-level correct count, except the serializer subtracts 1 when `place == 1` because Unity "counts the last turn"

### Normalization rules before write

Implemented in helper functions near the top of `views.py`.

- `Bug`, `Back`, and `AllBack*` card types are normalized to `Back`
- if `MoveX` or `Back` card data omits `thenValue`, the backend injects `thenValue=1`
- card metadata is extracted into `chosen_card_type`, `chosen_card_family`, and `chosen_card_tile_type`

### Persistence flow

Inside one transaction:

1. create `Run`
2. convert each Unity turn into an unsaved `TurnEvent`
3. bulk create all `TurnEvent`s
4. map created rows by `turn_index`
5. convert special trigger payloads into unsaved `SpecialTileTrigger`s
6. bulk create all triggers

### Data mapping details that matter

- `player_won` is derived as `place == 1`
- `elapsed_ms = runEndedUnixMs - runStartedUnixMs`
- negative elapsed time is clamped to `0`
- elapsed times over 2 hours are capped at `7_200_000`
- `game_map` stores `gameMap.mapTiles`
- `tile_before_type` uses Unity's `tileBefore.tileIndex`, not `tileType`
- `special_tile_type` uses `specialTile.tileIndex`
- `target_tile_type` is hard-coded to `0` because the Unity payload does not include it
- special tile movement delta is taken from Unity trigger payload for `insertRunData/`; canon supplied by you says clown is `-4` and skateboard is `+5`

### Important trust boundary

`insertRunData/` ignores `classroomKey` and `user` after validation. The only student identity actually enforced is `userID`.

That means the server currently trusts the client not to mismatch these fields.

### Error behavior

- serializer failure -> `400`
- database integrity problem -> `409`
- unexpected error -> `500`

## Alternative ingestion: `runs/ingest/`

### Why it exists

This endpoint is a cleaner, more backend-native run ingestion path that expects normalized snake_case field names and explicit `run_id` for idempotency.

### Key differences from `insertRunData/`

- requires client-supplied `run_id`
- returns `200` if the run already exists
- catches duplicate-key race conditions and also returns `200`
- does not populate `place` explicitly
- does not populate `game_map` explicitly
- expects already-normalized turn/trigger payloads rather than the Unity-specific nested shape

### Practical implication

It is safer for idempotent ingestion but currently produces less complete `Run` rows than the Unity-specific path.

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
