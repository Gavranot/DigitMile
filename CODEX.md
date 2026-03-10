# CODEX.md

Guidance for GPT Codex agents working in this repository.
Scope: repository root and all subdirectories.

## 1) Repository Overview
- Stack: Unity WebGL frontend + Django REST backend + PostgreSQL.
- Runtime entrypoint: Docker Compose (not Kubernetes).
- Backend path: `DigitMilePanel/`.
- Frontend/build artifacts: `DigitMile/`.
- Reverse proxy: `nginx-proxy/`.
- Backend is mounted/routed under `/panel/`.

## 2) Source of Truth Rule
- Prefer real runtime config over docs when conflicts exist.
- Canonical operational files:
  - `docker-compose.yml`
  - `docker-compose.localhost.yml`
  - `docker-compose.prod.yml`
  - `.github/workflows/build.yml`
  - `.github/workflows/deploy.yml`
  - `.github/workflows/deploy-to-environment.yml`

## 3) Docker Environments (Critical)

### Local HTTP (base compose)
- Command: `docker-compose up -d`
- Uses `docker-compose.yml` only.
- Exposes:
  - `frontend` on host `:80`
  - `backend` on host `:8000`
  - `db` on host `:5432`
- No `nginx-proxy` container in this mode.

### Local HTTPS (self-signed)
- Command: `docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d`
- Adds `nginx-proxy` built from `nginx-proxy/Dockerfile.localhost`.
- Routes:
  - `/` -> Unity frontend
  - `/panel/`, `/admin/`, `/i18n/`, `/static/` -> backend
- `frontend`/`backend` host ports are removed in this mode (`ports: !override []`).

### Production compose
- Command pattern: `docker compose -f docker-compose.yml -f docker-compose.prod.yml ...`
- Uses prebuilt images (Docker Hub), not source mounts.
- Adds `certbot` container and Let’s Encrypt volumes.
- Removes host port exposure from `db`, `backend`, `frontend`; traffic flows through `nginx-proxy`.
- `nginx-proxy/nginx.conf.production` is domain-specific (currently hardcoded for `digit.mile.mk`).

### Backend startup behavior (important)
- In `docker-compose.yml`, backend command runs on every container start:
  1. `python manage.py migrate`
  2. `python manage.py collectstatic --noinput`
  3. `python manage.py create_superuser`
  4. `gunicorn ...`
- Do not duplicate this logic in deployment scripts unless explicitly needed.

## 4) CI/CD Nuances (Important)

### Active deployment pipeline
- Main flow is manual dispatch via `.github/workflows/deploy-to-environment.yml`:
  1. Calls `build.yml` to build/push 3 images (`game`, `backend`, `nginx-proxy`).
  2. Calls `deploy.yml` to upload config and deploy remotely over SSH.

### Deploy behavior details (`deploy.yml`)
- Uploads only deployment config (`docker-compose*.yml`, `nginx-proxy/`) to `/var/www/digitmile`.
- Recreates `.env` on server from GitHub Secrets/Variables during deploy.
- Pulls `{TARGET_ENV}-latest` image tags and starts with compose overrides.
- Runs basic backend readiness check using `django.setup()` in container.
- SSL setup job runs only for `prod` and attempts cert bootstrap before container deploy.

### Legacy workflows present
- `.github/workflows/django.yml` and `.github/workflows/game.yml` exist but appear legacy/misaligned:
  - Trigger on `master`, but push-job condition in `django.yml` checks `refs/heads/main`.
  - Treat them as secondary unless user explicitly asks to use/fix them.

### Branch/tag and environment assumptions
- `deploy-to-environment.yml` defaults to `ref=master`.
- Deployment images are tagged as:
  - `{env}-latest`
  - `{env}-{git_sha}`

## 5) Kubernetes Status (Do Not Treat as Production-Ready)
- `k8s/` manifests exist but are not the active, reliable deployment path.
- Current practical status: Kubernetes is not configured/operational for production.
- Notable drift/inconsistencies inside `k8s/` include:
  - Placeholder domains (`yourdomain.com`) in ingress.
  - Health probes hitting `/health/` while app routes are namespaced under `/panel/health/`.
  - Image naming mismatch in prod overlay (`digitmile-webgl-game` vs `digitmile-game`).
  - Secrets/config values are not production-safe as committed examples.
- Unless explicitly requested, do not route deployment work through `k8s/`.

## 6) Backend Routing and API Conventions
- Django is served under `/panel/` (see `DigitMilePanel/digitmile/urls.py`).
- API root pattern: `/panel/api/...`
- CSRF flow used by Unity:
  - Fetch token: `/panel/api/fetchCSRFToken/`
  - Send header: `X-CSRFToken`
- `APPEND_SLASH=False`; do not casually add/remove trailing slash behavior.

## 7) Statistics and Visualizations (High-Impact Area)
This is a core product area. Treat changes here as high risk.

### Core files
- Analytics queries: `DigitMilePanel/digitmileapi/analytics.py`
- Dashboard view/context assembly: `DigitMilePanel/digitmileapi/views.py` (`teacher_statistics_dashboard`)
- Main dashboard template + Chart.js logic:
  - `DigitMilePanel/digitmileapi/templates/digitmileapi/teacher_statistics.html`
- Route entry:
  - `/panel/teacher/statistics/`

### Data model transition in progress
- Legacy model paths still exist (`RunStatistics`).
- New granular analytics models are also present (`Run`, `TurnEvent`, `SpecialTileTrigger`).
- Preserve backward compatibility unless task explicitly authorizes migration/removal.

### Safety rules for visualization work
- Keep JSON keys stable between `views.py` context and template JS readers.
- Do not rename chart container IDs without updating all JS wiring.
- Prefer adding fields over breaking/renaming existing schema consumed by UI.
- Validate role/permission filtering for teacher-scoped data.
- Be careful with heavy aggregations; optimize via DB-level `annotate`/`select_related`/`prefetch_related`.

## 8) Environment & Settings Notes
- Python: 3.12.
- Django: 5.2.
- DB: PostgreSQL 16.
- `DigitMilePanel/digitmile/settings.py` loads `.env` from `DigitMilePanel/.env`, while compose injects root `.env` values into container env.
- Production proxy and CSRF trusted origins are currently tuned around `digit.mile.mk`; domain changes require coordinated updates (nginx + env + Django settings).

## 9) Working Rules for Codex
- Keep patches focused; avoid broad refactors unless requested.
- Do not edit Unity build artifacts unless asked.
- Prefer Docker-based commands for backend verification.
- If touching CI/CD or deploy scripts, state assumptions clearly (target env, branch, image tags, domain).
- If task touches stats/visualization behavior, include a quick verification checklist in your response (query shape, context keys, chart render path).

## 10) Useful Commands
From repo root:
- Start local HTTP: `docker-compose up -d`
- Start local HTTPS: `docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d`
- Rebuild backend: `docker-compose up -d --build backend`
- Backend logs: `docker-compose logs -f backend`
- Run tests: `docker-compose exec backend python manage.py test`
- Run one app tests: `docker-compose exec backend python manage.py test digitmileapi`
- Apply migrations: `docker-compose exec backend python manage.py migrate`

## 11) When in Doubt
- Assume Docker Compose is the supported runtime/deploy path.
- Assume visualization/statistics regressions are high priority defects.
- Ask before introducing new tooling/dependencies.

## 12) Gameplay Canon (Cards, Levels, Map)
Use this as canonical behavior when implementing analytics, replay, ingestion, or seeding.

### Levels and decks
- Active level range is `1..6` for run analytics/replay logic.
- Deck definitions are in:
  - Primary: `DigitMilePanel/digitmileapi/templates/assets/Level{N}.json`
  - Legacy fallback: `DigitMile/assets/Level{N}.json`
- Level deck entries are `{ "cardName": "...", "count": <int> }`.
- Draw behavior:
  - Cards are drawn without replacement from current shuffled deck.
  - When deck is depleted, it is reshuffled and draw continues.
- Bag cards are present only in levels `5` and `6` (`NumberCardsInDeck=true` levels).

### gameMap schema
- `run.game_map` is a JSON list of tile snapshots:
  - `tileMapIndex` (position index)
  - `tileIndex` (texture/index enum value)
  - `tileType` (semantic tile type; use this for logic)
  - `special` (`"normal" | "clown" | "skateboard"`)
  - `special_delta` (`0`, `-4`, `+5`)
- Tile type meanings:
  - `0`: start/end tiles
  - `1,2,3,6`: normal tiles
  - `4`: clown tile (special move `-4`)
  - `5`: skateboard tile (special move `+5`)
- Tile type `0` is not used in card conditionals.

### Card payload format
Cards are stored as:
```json
{
  "type": "<CardTypeName>",
  "data": "[CardData: tileType=..., ifSign=..., ifValue=..., thenValue=..., elseValue=...]"
}
```
- Empty values in the data string mean the field is unused for that card.
- Parse `tileType`, `ifValue`, `thenValue`, `elseValue` as ints when non-empty.
- Parse `ifSign` as string when non-empty.

### Card type semantics
- `MoveX`
  - Uses `thenValue`.
  - Effect: move active player `+thenValue`.
  - If missing `thenValue`, default is `1`.
- `Back` / `Bug` / `AllBack*`
  - Normalize as `Back`.
  - Effect: move active player `-thenValue`.
  - If missing `thenValue`, default is `1`.
- `IfXMoveYElseMoveZ`
  - Uses `tileType`, `thenValue`, `elseValue`.
  - Condition: `player_tile_type == tileType`.
  - Effect: if true `+thenValue`, else `+elseValue`.
- `IfBagEqualXMoveYElseMoveZ`
  - Uses `ifValue`, `thenValue`, `elseValue`.
  - Condition: `bag_count == ifValue`.
- `IfBagLessXMoveYElseMoveZ`
  - Condition: `bag_count < ifValue`.
- `IfBagGreaterXMoveYElseMoveZ`
  - Condition: `bag_count > ifValue`.
- `BagCount`
  - Effect: move active player by current bag number.
  - Bag number is previous turn's `chosen_number`; default `1` on first turn.
- `ForXMoveY`
  - Uses `tileType`, `thenValue`.
  - Count players on that tile type as `player + bots` at turn start.
  - Effect applies only to active player: move `+(count * thenValue)`.

### Special tile chain behavior
- Special effects trigger after normal card movement and can chain.
- Clown tile (`4`) applies `-4`.
- Skateboard tile (`5`) applies `+5`.
- Replay should use recorded positions and recorded trigger events (no simulation).

### Seeding expectations for production-like data
- Seeded turns should include:
  - realistic `offered_cards` and `chosen_card` from level deck composition
  - deck depletion + reshuffle behavior
  - `offered_numbers` / `chosen_number` populated only for levels `5` and `6`
  - `game_map` with tile types and `special_delta` values aligned to above rules
