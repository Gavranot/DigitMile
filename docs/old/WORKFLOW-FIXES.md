# GitHub Actions Workflow Fixes

## Issues Fixed

### Issue 1: Build Context Error ❌
```
err: unable to prepare context: path "/var/www/digitmile/DigitMile" not found
```

**Root Cause:**
- `docker-compose.yml` has `build: context: ./DigitMile` and `context: ./DigitMilePanel`
- In production deployment, we only upload compose files, not source code
- Pre-built images come from Docker Hub, but Docker Compose still tried to validate build contexts
- The directories don't exist on the server

**Solution Applied:**
Updated `docker-compose.prod.yml` to override build contexts:

```yaml
backend:
  image: ${DOCKERHUB_USERNAME}/digitmile-backend:${TARGET_ENV}-latest
  build:
    context: .  # Changed from {} to point to current directory
  volumes: []   # Disable volume mounting in production

frontend:
  image: ${DOCKERHUB_USERNAME}/digitmile-game:${TARGET_ENV}-latest
  build:
    context: .

nginx-proxy:
  image: ${DOCKERHUB_USERNAME}/digitmile-nginx-proxy:${TARGET_ENV}-latest
  build:
    context: .
```

**Why This Works:**
- `context: .` points to the current directory (where docker-compose files are)
- Docker Compose validates this exists (it does - `/var/www/digitmile`)
- But the `image:` directive takes precedence, so it pulls from Docker Hub instead of building
- No actual build happens, just validation passes

### Issue 2: Certbot Service Not Found ❌
```
err: no such service: certbot
```

**Root Cause:**
- The `certbot` service is only defined in `docker-compose.prod.yml`
- The workflow command was: `docker compose run --rm certbot`
- This only loads the default `docker-compose.yml`, which doesn't have certbot

**Solution Applied:**
Updated `deploy.yml` to specify both compose files:

```yaml
# Before
docker compose run --rm certbot certonly --webroot ...
docker compose restart nginx-proxy

# After
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot certonly --webroot ...
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx-proxy
```

**Why This Works:**
- `-f docker-compose.yml -f docker-compose.prod.yml` loads both files
- Docker Compose merges them, making the `certbot` service available
- Commands can now find and run the certbot service

## Files Modified

1. **docker-compose.prod.yml**
   - Changed `build: {}` to `build: context: .` for all services
   - Added `volumes: []` to backend to disable code mounting in production
   - Added nginx-proxy image override

2. **.github/workflows/deploy.yml**
   - Updated certbot command to use both compose files
   - Updated nginx-proxy restart to use both compose files

3. **.env.example**
   - Added Django superuser environment variables

## Testing the Fixes

### Test 1: Verify Build Context Override
```bash
# On server
cd /var/www/digitmile

# This should NOT try to build, just pull images
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull

# This should start without build errors
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Test 2: Verify Certbot Works
```bash
# On server
cd /var/www/digitmile

# This should find the certbot service
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot --version
```

### Test 3: Full Deployment
```bash
# Trigger GitHub Actions workflow
# Go to: Actions → Deploy to Environment
# Select: environment = staging (test first!)
# Click: Run workflow

# Check logs for:
# ✓ No "path not found" errors
# ✓ No "no such service: certbot" errors
# ✓ Images pulled successfully
# ✓ Containers started
# ✓ Migrations completed
```

## How Production Deployment Works Now

```
GitHub Actions Workflow
    ↓
1. Build Phase (build.yml)
   - Builds images locally in GitHub runner
   - Context: Full source code from repo
   - Pushes to Docker Hub: gashmurble/digitmile-*:prod-latest
    ↓
2. Deploy Phase (deploy.yml)
   - Uploads ONLY compose files and nginx config to server
   - Does NOT upload source code
    ↓
3. Server Execution
   - docker-compose.yml: Defines services with local build contexts
   - docker-compose.prod.yml: Overrides with images from Docker Hub
   - Merged result: Pulls images, ignores local builds
    ↓
4. Container Startup
   - Images from Docker Hub contain ALL source code
   - No local source code needed on server
   - Migrations and collectstatic run automatically
    ↓
5. SSL Setup (first deploy only)
   - Uses both compose files to find certbot service
   - Requests certificate from Let's Encrypt
   - Reloads nginx with SSL
```

## What Gets Uploaded to Server

### During Deployment
```
/var/www/digitmile/
├── docker-compose.yml        ✅ Uploaded
├── docker-compose.prod.yml   ✅ Uploaded
├── nginx-proxy/              ✅ Uploaded
│   ├── nginx.conf.production
│   ├── nginx.conf.localhost
│   └── Dockerfile
└── .env                      ⚠️  Must be manually placed (contains secrets)
```

### NOT Uploaded (Built Into Images)
```
❌ DigitMile/          (in game image)
❌ DigitMilePanel/     (in backend image)
```

## Environment Variables for Superuser

The backend automatically creates a superuser on startup if these are set in `.env`:

```env
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@digit.mile.mk
DJANGO_SUPERUSER_PASSWORD=strong-password-here
```

This happens in the backend startup command:
```yaml
command: >
  sh -c "python manage.py migrate &&
         python manage.py collectstatic --noinput &&
         python manage.py create_superuser &&
         gunicorn ..."
```

The `create_superuser` command:
- Checks if user already exists
- If not, creates user with credentials from env vars
- If yes, skips creation
- Never fails the startup

## Deployment Checklist

Before deploying via GitHub Actions:

- [ ] `.env` file uploaded to server at `/var/www/digitmile/.env`
- [ ] `.env` contains all required variables (use `.env.production` as template)
- [ ] DNS points to server: `digit.mile.mk → server-ip`
- [ ] Ports 80 and 443 open on firewall
- [ ] GitHub secrets configured:
  - `DOCKERHUB_USERNAME` = gashmurble
  - `DOCKERHUB_TOKEN` = (your token)
  - `prod_SSH_PRIVATE_KEY` = (SSH key)
- [ ] GitHub variables configured:
  - `prod_HOST` = digit.mile.mk
  - `prod_USERNAME` = ubuntu
  - `prod_PORT` = 22
  - `DOMAIN` = digit.mile.mk
  - `SSL_EMAIL` = admin@digit.mile.mk

## Quick Reference Commands

### On Server (Manual Deployment)
```bash
cd /var/www/digitmile

# Pull latest images
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull

# Start services
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# View logs
docker compose logs -f backend

# Request SSL certificate (first time)
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot certonly --webroot \
  --webroot-path=/var/www/certbot \
  --email admin@digit.mile.mk \
  --agree-tos \
  -d digit.mile.mk -d www.digit.mile.mk

# Restart nginx after SSL
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx-proxy
```

### Via GitHub Actions
```bash
# Go to: GitHub → Actions → Deploy to Environment
# Select:
#   - ref: master
#   - environment: staging (test first) or prod
# Click: Run workflow
```

## Summary

✅ **Build context issue** - FIXED by setting `context: .` in prod override
✅ **Certbot service** - FIXED by using both compose files in commands
✅ **Volume mounting** - DISABLED in production (no source code on server)
✅ **Superuser creation** - ADDED env vars to .env.example
✅ **Documentation** - UPDATED with correct commands

**Your workflows should now deploy successfully!** 🚀

## Next Steps

1. **Test deployment to staging first**
   ```bash
   # Set up staging environment variables in GitHub
   # Run: Deploy to Environment → staging
   ```

2. **Verify everything works**
   - Check containers are running
   - Test game loads
   - Test admin panel
   - Verify migrations ran

3. **Deploy to production**
   ```bash
   # Run: Deploy to Environment → prod
   ```

4. **Monitor deployment**
   ```bash
   # SSH to server
   ssh ubuntu@digit.mile.mk
   cd /var/www/digitmile
   docker compose logs -f
   ```
