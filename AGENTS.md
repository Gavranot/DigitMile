# AGENTS.md

Guidance for agentic coding assistants working in this repo.
Scope: repository root and all subdirectories.

## Repo Overview
- Full-stack product: Unity WebGL frontend + Django REST backend.
- Reverse proxy via nginx; backend served under `/panel/`.
- Backend code lives in `DigitMilePanel/`.
- Unity build artifacts are in `DigitMile/`.
- Docker Compose is the primary dev runtime.

## Key Paths
- `DigitMilePanel/digitmile/`: Django project settings/urls/wsgi.
- `DigitMilePanel/digitmileapi/`: Main Django app (models, views, serializers, forms).
- `DigitMile/`: Unity WebGL build + nginx config.
- `nginx-proxy/`: SSL termination reverse proxy.
- `.github/workflows/`: CI/CD (build/deploy).

## Build / Run Commands (from repo root)
- Start all services (HTTP): `docker-compose up -d`.
- Start all services (HTTPS local): `docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d`.
- Rebuild all services: `docker-compose up -d --build`.
- Rebuild backend only: `docker-compose up -d --build backend`.
- Stop services: `docker-compose down`.
- View backend logs: `docker-compose logs -f backend`.

## Backend Management Commands
- Migrate DB: `docker-compose exec backend python manage.py migrate`.
- Create superuser: `docker-compose exec backend python manage.py createsuperuser`.
- Django shell: `docker-compose exec backend python manage.py shell`.
- Collect static: `docker-compose exec backend python manage.py collectstatic --noinput`.

## Tests
- Run all Django tests in container: `docker-compose exec backend python manage.py test`.
- Run tests locally (venv): `python manage.py test` from `DigitMilePanel/`.
- Run a single app: `docker-compose exec backend python manage.py test digitmileapi`.
- Run a single test case: `docker-compose exec backend python manage.py test digitmileapi.tests.MyTestCase`.
- Run a single test method: `docker-compose exec backend python manage.py test digitmileapi.tests.MyTestCase.test_method`.
- No extra test runner configured (uses Django's default `unittest`).

## Lint / Format
- No linting or formatting tool is configured in repo.
- Keep formatting consistent with existing code (4-space indent).
- If adding tools, discuss first; do not introduce new linters by default.

## Cursor / Copilot Rules
- No `.cursorrules`, `.cursor/rules/`, or `.github/copilot-instructions.md` found.

## Python/Django Style
- Python version: 3.12 (see Dockerfile).
- Use 4 spaces; avoid tabs.
- Keep line lengths reasonable; wrap long strings with parentheses.
- Prefer `f"..."` for string formatting.
- Avoid one-letter variable names except trivial indices.
- Keep functions and methods small and focused.
- Keep top-level definitions separated by a blank line.

## Imports
- Order: standard library, third-party, local app imports.
- Group imports with a blank line between groups.
- Prefer explicit imports over wildcard imports.
- In Django apps, use relative imports within the app (`from .models import ...`).

## Naming Conventions
- Classes: `PascalCase`.
- Functions/methods/variables: `snake_case`.
- Constants: `UPPER_SNAKE_CASE`.
- Django model fields: `snake_case`.
- Serializer fields mirror model names or API contracts.

## Django Models
- Keep model `__str__` methods concise and user-friendly.
- Use model managers for filtered querysets when helpful.
- Override `save()` only when needed; call `super().save()`.
- Use `clean()` for validation and raise `ValidationError`.
- Prefer `related_name` on relations for clarity.
- Use `unique_together` or `UniqueConstraint` consistently with existing style.

## Forms
- For complex multi-model input, use `forms.Form` with manual handling.
- Use `clean()` for cross-field validation.
- Keep validation messages explicit and user-facing.

## API / DRF
- Use DRF `APIView` or `ViewSet` as existing patterns show.
- Return `Response` with explicit `status` codes.
- Validate input with serializers; return `400` on invalid data.
- Keep throttle/permission classes declared near view class definition.
- Use `select_related`/`prefetch_related` when loading related models.

## Error Handling
- Catch specific exceptions (`DoesNotExist`, `ValidationError`) first.
- Avoid broad `except Exception` unless you re-raise or log.
- Log errors with `logging.getLogger(__name__)` instead of `print`.
- When returning `500`, include a generic message only.

## Logging
- Use the project logger; logs go to stdout.
- Prefer `logger.info/warning/error` over `print`.

## Security / CSRF
- Unity clients use the fetch-and-header CSRF flow.
- Fetch token from `/panel/api/fetchCSRFToken/`.
- Unity sends token in `X-CSRFToken` header.
- `APPEND_SLASH=False`; avoid adding trailing slashes to API URLs.

## Database / Migrations
- Run migrations whenever models change.
- Keep data migrations minimal and reversible.
- Avoid raw SQL unless absolutely necessary.
- Use `django.db.transaction` for multi-step writes.

## Templates / Frontend
- Admin/UI templates live under app template folders.
- Keep HTML changes minimal; match existing classes/structure.
- Unity build artifacts are static; do not edit unless asked.

## Docker Notes
- Backend code is mounted into container at `/app`.
- `.env` lives at repo root; copy from `DigitMilePanel/.env.example`.
- Database service is `db` and backend service is `backend`.

## Testing Tips
- Use Docker for tests to match dependencies (Postgres, env).
- If a test requires DB fixtures, use Django factories/fixtures.
- Keep tests deterministic; avoid relying on external services.

## Change Discipline
- Keep changes focused on the requested scope.
- Avoid refactors unless necessary for the task.
- Preserve existing public API shapes used by Unity.
- Update docs only when behavior changes.

## Helpful Reference Commands
- Open backend shell: `docker-compose exec backend sh`.
- View DB shell: `docker-compose exec db psql -U digitmile_user digitmile`.
- Backup DB: `docker-compose exec db pg_dump -U digitmile_user digitmile > backup.sql`.
- Restore DB: `docker-compose exec -T db psql -U digitmile_user digitmile < backup.sql`.

## Notes for Agents
- Always check for nested `AGENTS.md` in subdirectories.
- Obey any new Cursor/Copilot rules if they appear.
- Ask before adding new dependencies or tooling.
- Prefer minimal, readable patches.

## Versioning
- Backend uses Django 5.2 and DRF.
- Database is PostgreSQL 16.
- Container images are built via GitHub Actions.
