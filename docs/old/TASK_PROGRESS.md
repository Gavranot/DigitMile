# Teacher Statistics Performance Worklog

Date: 2026-02-15

## Goal
Reduce Gunicorn timeouts for `/panel/teacher/statistics/` by removing eager heavy analytics work from initial page render and optimizing expensive analytics paths.

## Progress
- [x] Create task tracker
- [x] Add denormalized `TurnEvent` card metadata fields (`type`, `family`, `tile_type`)
- [x] Backfill existing `TurnEvent` rows via migration
- [x] Fix empty `student_ids` scope edge case (prevent global scans)
- [x] Optimize `foreach_tile_context_usage_by_level` query path
- [x] Add lazy on-demand analytics endpoint for teacher dashboard
- [x] Cache analytics payloads by filter scope
- [x] Load analytics/turn-insight charts only when expanded in UI
- [x] Run quick validation checks

## Notes
- Keep existing API contracts stable where possible.
- Prioritize compatibility for existing historical data.
