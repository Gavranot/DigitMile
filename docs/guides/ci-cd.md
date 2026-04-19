# CI / CD

DigitMile ships via five GitHub Actions workflows in `.github/workflows/`. The load-bearing path is: **`deploy-to-environment.yml` → `build.yml` → `deploy.yml`**. The two legacy workflows (`django.yml`, `game.yml`) are path-triggered auto-builds on `master`; they do not deploy.

## Workflow map

| File | Trigger | What it does |
|------|---------|--------------|
| `deploy-to-environment.yml` | Manual (`workflow_dispatch`) | Orchestrator. Takes `ref` + `environment` (`development`/`staging`/`prod`) inputs and chains `build.yml` → `deploy.yml`. |
| `build.yml` | `workflow_call` | Builds and pushes three images to Docker Hub: `digitmile-game`, `digitmile-backend`, `digitmile-nginx-proxy`. Uses buildx with registry layer caching. |
| `deploy.yml` | `workflow_call` | Uploads `docker-compose*.yml` + `nginx-proxy/` + `benchmarks/` to the server via SCP, runs the Let's Encrypt init on first prod deploy, writes `.env` from secrets/vars, pulls the images, and runs `docker compose up -d`. |
| `django.yml` | `push` to `master` with `DigitMilePanel/**` changes, or any PR touching `DigitMilePanel/**` | Installs backend deps on Python 3.12. Does **not** currently run the test suite. |
| `game.yml` | `push` to `master` with `DigitMile/**` changes | Builds + pushes a `latest`-tagged game image directly (parallel to `build.yml`). |

## How to trigger a deploy

1. Actions → **Deploy to Environment**.
2. `ref`: branch or tag to deploy.
3. `environment`: `development`, `staging`, or `prod`.
4. Run.

The same workflow is the only supported way to promote a build — there is no auto-deploy on merge.

## Image tags

`build.yml` pushes two tags per image per run:

- `<docker-hub-user>/<image>:<TARGET_ENV>-latest` — the rolling "current" tag the deploy pulls.
- `<docker-hub-user>/<image>:<TARGET_ENV>-<commit-sha>` — immutable, useful for rollback.

The deploy server re-tags `digitmile-backend:<TARGET_ENV>-latest` as the local alias `digitmile-backend:latest` so the benchmark compose file can find it without substitution.

## Secrets and Vars

`deploy.yml` composes `.env` on the target server from repo **secrets** (sensitive) and **vars** (non-sensitive). Multi-env values use the per-env prefix pattern (`{ENV}_HOST`, `{ENV}_USERNAME`, `{ENV}_PORT`, `{ENV}_SSH_PRIVATE_KEY`).

### Secrets (required)
- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `DB_USER`, `DB_PASS`
- `DJANGO_SECRET_KEY`, `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`
- `EMAIL_HOST_PASSWORD`
- `GOOGLE_MAPS_API_KEY`
- per env: `DEVELOPMENT_SSH_PRIVATE_KEY`, `STAGING_SSH_PRIVATE_KEY`, `PROD_SSH_PRIVATE_KEY`

### Vars (required)
- `DB_HOST`, `DB_NAME`, `DB_PORT`
- `SITE_URL`, `ALLOWED_HOSTS`, `SERVER_IP`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_BACKEND`, `EMAIL_USE_TLS`
- `DEBUG`
- per env: `DEVELOPMENT_HOST`, `DEVELOPMENT_USERNAME`, `DEVELOPMENT_PORT` (and `STAGING_*`, `PROD_*`)
- `DOMAIN`, `SSL_EMAIL` (used by the prod-only `setup-ssl` job)

## SSL init behavior (prod only)

The `setup-ssl` job inspects `certbot/conf/live/<DOMAIN>/fullchain.pem` on the target server:

1. If a valid Let's Encrypt cert exists, it skips.
2. If the cert is self-signed or missing, it stops the compose stack, frees port 80, runs `certbot certonly --standalone` inside a transient container, and writes the issued cert into `./certbot/conf/`.

The compose stack's `nginx-proxy` service mounts `./certbot/conf` as `/etc/letsencrypt` and the long-running `certbot` service handles renewal (`while :; do certbot renew; sleep 12h; done`).

## Known gotchas

- `django.yml` currently installs backend dependencies but does **not** run the test suite. If you want CI to fail on a broken test, add `python manage.py test digitmileapi` to its `test` job.
- `django.yml`'s `build-and-push` job has `if: github.ref == 'refs/heads/main'`, but the workflow triggers on `branches: [master]` — so this job never runs. It's redundant with `build.yml` and can safely be removed.
- `game.yml` pushes to `:latest` (not to `:<env>-latest`), which is not the tag `deploy.yml` pulls. Treat it as a separate auto-build pipeline, not as part of the deploy path.
- The deploy writes `.env` by `printf`-ing pre-formatted blocks; if you rename a var in `docker-compose.yml` or `settings.py`, update the corresponding block in `deploy.yml` too or the server won't pick up the new value.
