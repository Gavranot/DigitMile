# DigitMilePanel Backend Docs

Last updated: 2026-03-12

This documentation set is a fresh backend-focused map of the Django implementation in `DigitMilePanel/`, built from source inspection rather than the older iterative docs in `DigitMilePanel/docs/`.

## What to read first

- [`docs/backend-architecture-overview.md`](backend-architecture-overview.md) - runtime layout, major modules, and end-to-end flows.
- [`docs/backend-data-model.md`](backend-data-model.md) - entities, relationships, constraints, lifecycle states, and stored game data.
- [`docs/backend-ingestion-and-api.md`](backend-ingestion-and-api.md) - API endpoints, Unity payload ingestion, teacher APIs, and replay data flow.
- [`docs/backend-analytics-and-dashboard.md`](backend-analytics-and-dashboard.md) - how statistics are computed and how the teacher dashboard consumes them.
- [`docs/backend-registration-and-admin-workflows.md`](backend-registration-and-admin-workflows.md) - school and teacher registration, approval/rejection, permissions, and admin behavior.
- [`docs/backend-operations-and-config.md`](backend-operations-and-config.md) - environment, deployment, logging, caching, security posture, and troubleshooting.
- [`docs/weekly-rollup-replay-refactor-prd.md`](weekly-rollup-replay-refactor-prd.md) - detailed product and implementation plan for weekly analytics rollups plus indefinite replay archives.
- [`docs/weekly-rollup-replay-schema-spec.md`](weekly-rollup-replay-schema-spec.md) - concrete schema proposal and metric-to-rollup mapping for the refactor.
- [`docs/next-phase-implementation-checklist.md`](next-phase-implementation-checklist.md) - explicit implementation checklist for the next analytics, ingest, and benchmark phase.
- [`docs/weekly-rollup-operator-runbook.md`](weekly-rollup-operator-runbook.md) - operator commands, benchmark workflow, archive troubleshooting, and manual phase validation map.
- [`docs/hot-week-load-testing-implementation-plan.md`](hot-week-load-testing-implementation-plan.md) - detailed implementation plan for true hot-week concurrent read/write load testing.
- [`docs/hot-week-load-testing-execution-checklist.md`](hot-week-load-testing-execution-checklist.md) - implementation ticket checklist for the hot-week load-testing plan.
- [`docs/glossary.md`](glossary.md) - backend and gameplay terms used across the docs.

## Quick orientation

- Django project package: `DigitMilePanel/digitmile/`
- Main app: `DigitMilePanel/digitmileapi/`
- Public backend mount point: `/panel/`
- API mount point: `/panel/api/`
- Current analytics source of truth: `Run`, `TurnEvent`, and `SpecialTileTrigger`
- Legacy analytics path still present: `RunStatistics`
- Teacher UI surface: custom Django-admin-based templates plus JSON endpoints for chart data

## Highest-value implementation truths

- The backend currently carries two gameplay data pipelines: the legacy `RunStatistics` model and the newer full-fidelity run pipeline (`Run` -> `TurnEvent` -> `SpecialTileTrigger`).
- The teacher dashboard uses the newer run pipeline, not `RunStatistics`.
- Teacher registration creates a staff user immediately, even while the teacher record stays `PENDING`; the code intentionally allows pending teachers to log in and work.
- Schools and teachers are soft-state managed through `PENDING` / `APPROVED` / `REJECTED`; rejection disables access but preserves classrooms, students, and gameplay history.
- Bag-number analytics reflect the rule that the current turn's bag number is the number chosen at the end of the previous turn, with default `1` on the first turn and usage introduced in levels 5 and 6.
- `wasCorrect` means the player chose a card, reasoned about the resulting movement distance, and clicked the tile exactly that many spaces away.
- Special-tile canon used by the new docs is clown `-4` and skateboard `+5`.

## Suggested reading paths

- New engineer onboarding: architecture -> data model -> registration/admin workflows -> analytics
- Unity ingestion debugging: ingestion/API -> data model -> analytics -> glossary
- Teacher dashboard changes: analytics -> ingestion/API -> templates section inside registration/admin workflows
- Production/ops work: operations/config -> architecture overview
