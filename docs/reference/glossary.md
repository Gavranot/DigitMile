# Backend Glossary

Last updated: 2026-03-09

## Why this file exists

Older docs use overlapping terms for the same concepts. This glossary fixes the vocabulary used in the new backend docs.

## Terms

- `School` - institution record stored in Django; can be `PENDING`, `APPROVED`, or `REJECTED`.
- `Teacher` - teacher profile linked to a Django `User`; also has `PENDING`, `APPROVED`, and `REJECTED` statuses.
- `TeacherSchoolAssignment` - through-model joining a teacher to a school and storing `years_at_school`.
- `Classroom` - teacher-owned class container with a `classroom_key` used by the game client.
- `Student` - player/student record belonging to exactly one classroom.
- `RunStatistics` - legacy coarse-grained gameplay summary model.
- `Run` - current canonical record for one full gameplay session.
- `TurnEvent` - one move/turn inside a run.
- `SpecialTileTrigger` - one chained special tile effect attached to a turn.
- `classroom_key` - human-shareable key used by the Unity client to locate a classroom and student roster.
- `player_won` - backend boolean representation of whether a run was won; usually derived from `place == 1`.
- `place` - player's relative final standing in a run; turn rows also store `place_before` and `place_after`.
- `correct move` / `wrong move` - Unity-provided correctness judgment for a turn; Django stores it and derives analytics from it.
- `chosen_card` - the actual card selected by the player on a turn, stored as JSON.
- `offered_cards` - the full set of cards shown to the player for a turn.
- `chosen_card_type` - normalized concrete card type extracted from `chosen_card`.
- `chosen_card_family` - broader grouping used for analytics (`move`, `back`, `conditional_tile`, etc.).
- `tile_before_index` - map position before the turn.
- `tile_before_type` - tile type at the player's position before the turn.
- `tile_after_index` - player position after the move and any resolved effects.
- `game_map` - per-run snapshot of the board tiles used for replay and context-aware analytics.
- `bag number` - the active number for a turn; it is the number chosen at the end of the previous turn, defaulting to `1` on the first turn.
- `offered_numbers` - numbers presented for selection during number-choice turns.
- `chosen_number` - number selected at the end of a turn in levels 5 and 6; it becomes the next turn's bag number.
- `conditional tile card` - family of cards whose behavior depends on the tile type condition being met.
- `bag conditional card` - family of cards whose behavior depends on the bag number condition being met.
- `else rate` - percent of conditional-card turns where the condition was not met, so the else branch would have applied.
- `ForXMoveY` / `foreach tile` - card family whose move amount depends on how many players are on a target tile type.
- `Back` card - normalized family that includes `Back`, `Bug`, and `AllBack*` variants.
- `special tile` - gameplay tile with an automatic movement effect; clown is the backward penalty tile (`-4`) and skateboard is the forward reward tile (`+5`).
- `analytics section` - lazy-loaded dashboard payload containing high-level run charts.
- `turn insights section` - lazy-loaded dashboard payload containing card-family, conditional, special-chain, and number-choice charts.
- `teacher dashboard` - `teacher_statistics.html` plus its JSON data endpoint and supporting summary logic.
- `run replay` - the page that visualizes a single run's board, turns, and trigger chain using `run_data_json`.
- `soft rejection` - access disablement by status and `User.is_active` without deleting domain records.

## Ambiguous terms intentionally avoided

- `statistics` by itself - ambiguous because the codebase has both legacy `RunStatistics` and modern analytics over `Run`.
- `teacher school` - use `TeacherSchoolAssignment` when referring to the join record.
- `game stats` - specify whether you mean legacy `RunStatistics`, modern `Run` summaries, or dashboard heuristics.
