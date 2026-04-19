# Deployment Guide

How to bring DigitMile up on a fresh production server. Local development is covered by `docs/getting-started.md`; day-2 operations by `docs/guides/operations.md`; TLS by `docs/guides/ssl.md`; CI by `docs/guides/ci-cd.md`.

## Target topology

```
            ┌──────────────────────────────────┐
            │       nginx-proxy (443/80)       │
            │  Let's Encrypt + reverse proxy   │
            └───────────┬──────────────────────┘
                        │
        ┌───────────────┼──────────────────┐
        ▼                                  ▼
  frontend (nginx, Unity WebGL)     backend (Gunicorn, 5 workers)
                                          │
                                          ▼
                                    pgbouncer (transaction pooling)
                                          │
                                          ▼
                                    db (postgres:16-alpine)
                                          ▲
                                          │
                                    flusher ──▶ redis (ingest buffer + cache)
```

Six always-on services (`db`, `redis`, `pgbouncer`, `backend`, `flusher`, `frontend`) plus `nginx-proxy` and `certbot` in production overlay.

## Prerequisites

- Ubuntu-ish host with Docker + Docker Compose v2.
- Domain with an A record pointing to the server IP.
- Inbound TCP 80 and 443 open.
- A Docker Hub account (or GHCR — the GH Actions flow defaults to Docker Hub; see `docs/guides/ci-cd.md`).

## Option A — Deploy via GitHub Actions (recommended)

The `Deploy to Environment` workflow handles build, SSL init, and container deploy. See `docs/guides/ci-cd.md` for which secrets and vars to configure.

1. **Configure GitHub secrets/vars** (see `docs/reference/configuration.md` §"What the CI pipeline writes" for the full list).
2. **Trigger the workflow**: Actions → *Deploy to Environment* → pick branch + environment (`development` / `staging` / `prod`) → Run.
3. **First deploy only**: the `setup-ssl` job runs standalone-mode certbot to issue a Let's Encrypt cert (prod only). Subsequent deploys skip this if a valid cert exists.
4. The `deploy-containers` job SSHes to the server, writes `.env` from the configured secrets/vars, pulls the new images, and runs `docker compose up -d` with the prod overlay.

## Option B — Manual first-run on the server

### 1. Clone and seed `.env`

```bash
ssh you@server
sudo mkdir -p /var/www/digitmile && sudo chown $USER /var/www/digitmile
cd /var/www/digitmile
git clone <repo-url> .
cp .env.production .env
```

Edit `.env`. Set the full set from `docs/reference/configuration.md`. At minimum:

```
DB_NAME=digitmile
DB_USER=digitmile
DB_PASS=<strong-random>
DB_HOST=pgbouncer
DB_PORT=5432

DJANGO_SECRET_KEY=<long-random>
DEBUG=False
ALLOWED_HOSTS=your-domain.tld
SITE_URL=https://your-domain.tld

DJANGO_SUPERUSER_USERNAME=<admin>
DJANGO_SUPERUSER_PASSWORD=<strong-random>
DJANGO_SUPERUSER_EMAIL=<you@domain>

DOCKERHUB_USERNAME=<docker-user>
DOCKERHUB_TOKEN=<docker-pat>
BENCHMARK_BACKEND_IMAGE=<docker-user>/digitmile-backend:prod-latest
```

### 2. Build or pull the images

Either `git clone` and `docker compose build`, or `docker login && docker pull` the pre-built images produced by `build.yml`.

### 3. First-time SSL

```bash
./scripts/init-letsencrypt.sh your-domain.tld you@domain.com
```

This spins up certbot in standalone mode, issues the cert, and places it under `./certbot/conf/live/<domain>/`. See `docs/guides/ssl.md` for the self-signed variant.

### 4. Start the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The `backend` container's boot command runs:

```
DB_HOST=db python manage.py migrate
python manage.py collectstatic --noinput
python manage.py create_superuser
gunicorn ... --workers 5
```

The explicit `DB_HOST=db` bypasses PgBouncer for migrations — Django's `migrate` command takes advisory locks that don't survive transaction-pooling. App traffic still goes through `pgbouncer`.

### 5. Verify

```bash
curl -I https://your-domain.tld/                    # game
curl -I https://your-domain.tld/panel/health/       # {"status":"healthy"}
curl -I https://your-domain.tld/panel/admin/login/  # redirect to login
```

## Post-deploy checks

- `docker compose ps` — all six services (`db`, `redis`, `pgbouncer`, `backend`, `flusher`, `frontend`) + `nginx-proxy` + `certbot` should be `Up`.
- `docker compose logs flusher | tail` — confirm batches are being flushed (or at least the "queue empty, sleeping" line).
- `docker compose exec backend python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(is_superuser=True).count())"` — should print at least `1`.

## Rollback

Keep the previous image tagged `prod-previous`:

```bash
docker tag <user>/digitmile-backend:prod-latest <user>/digitmile-backend:prod-previous
```

To roll back, re-tag the known-good image back to `prod-latest` on the server and `docker compose up -d`. Note: if the rollback crosses a database migration that isn't reverse-safe, roll back the DB first (out of scope for this doc).

## Fully-fresh production (destroy all data)

Only do this before any real user traffic:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
docker volume rm digitmile_postgres_data digitmile_redis_data digitmile_replay_archives_data
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Replace `digitmile_` with your compose project prefix if different (`docker volume ls`).

## Kubernetes

There is a `k8s/` scaffold in the repo. It is **not** a live deploy path — treat it as a stub for future work. Before it could replace the docker-compose stack you would need real secret management (e.g. External Secrets), image tags wired to CI, a working Ingress + TLS solution, and a tested deploy pipeline. None of that is in place today.
