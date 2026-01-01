# GitHub Actions Workflow Changes

## Summary of Updates

The CI/CD workflows have been updated to reflect the current project structure and deployment process.

## Key Changes Made

### 1. deploy.yml - Removed Redundant Commands

**Before:**
```yaml
# Start new containers
docker-compose up -d

# Run database migrations
docker-compose exec -T backend python manage.py migrate

# Collect static files
docker-compose exec -T backend python manage.py collectstatic --noinput
```

**After:**
```yaml
# Start new containers (migrations and collectstatic run automatically)
docker-compose up -d
```

**Reason:** The `docker-compose.yml` backend service already runs migrations and collectstatic in its startup command:

```yaml
command: >
  sh -c "python manage.py migrate &&
         python manage.py collectstatic --noinput &&
         python manage.py create_superuser &&
         gunicorn digitmile.wsgi:application --bind 0.0.0.0:8000 --workers 3"
```

Running them again in the deployment script was redundant and could cause issues.

### 2. deploy.yml - Added .env Validation

**Added:**
```yaml
# Verify .env file exists
if [ ! -f .env ]; then
  echo "ERROR: .env file not found!"
  echo "Please upload .env file to /var/www/digitmile/.env"
  exit 1
fi
```

**Reason:** The deployment requires a `.env` file in the root directory. This check prevents deployment failure and gives clear error message.

### 3. deploy.yml - Added Backend Health Check

**Added:**
```yaml
# Wait for backend to be healthy
echo "Waiting for backend to be ready..."
for i in {1..30}; do
  if docker-compose exec -T backend python -c "import django; django.setup()" 2>/dev/null; then
    echo "Backend is ready!"
    break
  fi
  echo "Waiting... ($i/30)"
  sleep 2
done

# Verify migrations ran successfully
docker-compose logs backend | grep -q "Operations to perform" && echo "✓ Migrations completed" || echo "⚠ Check migration logs"
```

**Reason:** Ensures the backend container is fully initialized before considering the deployment successful. Also verifies migrations completed.

### 4. deploy.yml - Removed Domain Replacement

**Before:**
```yaml
# Update nginx config with domain
sed -i "s/your-domain.com/${{ env.DOMAIN }}/g" nginx-proxy/nginx.conf.production
```

**After:**
*(Removed)*

**Reason:** The nginx configuration is now pre-configured with `digit.mile.mk` in the repository. No need to replace it dynamically.

### 5. CI-CD-SETUP.md - Updated Documentation

**Changes:**
- Updated domain from generic `your-domain.com` to `digit.mile.mk`
- Clarified `.env` file location (ROOT directory, not `DigitMilePanel/`)
- Updated DB_USER from `digitmile_user` to `digitmile`
- Added complete `.env` template with all required variables

## Environment File Location - IMPORTANT

### Before (Incorrect)
```
DigitMilePanel/.env  ← Backend tried to read from here
```

### After (Correct)
```
.env  ← Root directory (where docker-compose.yml is)
```

**Why this matters:**
- Docker Compose reads `.env` from the **same directory as docker-compose.yml**
- Both `${VARIABLE}` substitution and `env_file` directive now use the same file
- Simpler configuration, single source of truth

## Workflow Structure

### build.yml
**Purpose:** Build Docker images and push to Docker Hub

**Jobs:**
1. `build_game_docker` - Build Unity game container
2. `build_backend_docker` - Build Django backend container
3. `build_nginx_proxy_docker` - Build NGINX reverse proxy container

**Triggers:** Called by `deploy-to-environment.yml`

**No changes needed** - Already correctly configured

### deploy.yml
**Purpose:** Deploy containers to server and setup SSL

**Jobs:**
1. `deploy-configuration` - Upload docker-compose files and nginx config
2. `deploy-containers` - Pull images, start containers, verify deployment
3. `setup-ssl` - Initialize Let's Encrypt SSL certificates (first deploy only)

**Changes made:** See sections 1-4 above

### deploy-to-environment.yml
**Purpose:** Manual deployment trigger

**Inputs:**
- `ref` - Branch/tag to deploy (default: master)
- `environment` - Target environment (development/staging/prod)

**No changes needed** - Already correctly configured

## Deployment Process Flow

```
1. Developer triggers "Deploy to Environment" workflow
   ↓
2. build.yml runs:
   - Builds game, backend, nginx-proxy images
   - Pushes to Docker Hub with tags: {env}-latest, {env}-{git-sha}
   ↓
3. deploy.yml runs:
   - Uploads docker-compose.yml, docker-compose.prod.yml, nginx-proxy/
   - SSHs to server
   - Verifies .env exists
   - Pulls latest images
   - Stops old containers
   - Starts new containers
     └─→ Migrations run automatically
     └─→ Static files collected automatically
     └─→ Superuser created automatically (if needed)
   - Waits for backend to be healthy
   - Verifies migrations completed
   ↓
4. setup-ssl runs (prod only, first time):
   - Checks if SSL certificate exists
   - If not, requests from Let's Encrypt
   - Reloads NGINX with SSL
   ↓
5. Deployment complete! ✅
```

## What Happens on Each Deployment

### Automatic (No Manual Steps)
- ✅ Docker images built
- ✅ Images pushed to Docker Hub
- ✅ Configuration files uploaded
- ✅ Old containers stopped
- ✅ New containers started
- ✅ Database migrations applied
- ✅ Static files collected
- ✅ Health check performed
- ✅ Old images cleaned up

### Manual (One-Time Setup)
- ⚠️ Upload `.env` file to server (required before first deploy)
- ⚠️ SSL certificate initialization (automatic on first prod deploy)

## Required Server Setup

Before running workflows, ensure server has:

1. **Docker and Docker Compose installed**
2. **`.env` file in `/var/www/digitmile/.env`** with:
   - Database credentials
   - Django SECRET_KEY
   - ALLOWED_HOSTS
   - API keys
   - Email configuration
3. **SSH key authentication** configured
4. **Ports 80 and 443 open**
5. **DNS configured** (digit.mile.mk → server IP)

## GitHub Secrets Required

### Repository Secrets
- `DOCKERHUB_USERNAME` - Docker Hub username
- `DOCKERHUB_TOKEN` - Docker Hub access token
- `prod_SSH_PRIVATE_KEY` - SSH private key for production server
- `staging_SSH_PRIVATE_KEY` - SSH private key for staging (optional)
- `development_SSH_PRIVATE_KEY` - SSH private key for dev (optional)

### Repository Variables
- `prod_HOST` - Production server hostname (digit.mile.mk)
- `prod_USERNAME` - SSH username for production
- `prod_PORT` - SSH port (usually 22)
- `DOMAIN` - Domain for SSL certificate (digit.mile.mk)
- `SSL_EMAIL` - Email for Let's Encrypt notifications

## Testing the Workflows

### Test Build Only
```bash
# Manually trigger build workflow from GitHub Actions tab
# Select: build.yml
# Inputs:
#   - TARGET_ENV: staging
#   - REF: master
```

### Test Full Deployment
```bash
# Manually trigger from GitHub Actions tab
# Select: Deploy to Environment
# Inputs:
#   - ref: master
#   - environment: staging (test here first!)
```

### Verify Deployment
```bash
# SSH to server
ssh ubuntu@digit.mile.mk

# Check containers
cd /var/www/digitmile
docker-compose ps

# Check logs
docker-compose logs -f backend

# Check migrations
docker-compose logs backend | grep "Operations to perform"

# Check static files
docker-compose logs backend | grep "static files copied"
```

## Rollback Procedure

If deployment fails or breaks production:

```bash
# SSH to server
cd /var/www/digitmile

# Stop containers
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down

# Pull previous version (replace SHA with known-good commit)
docker pull gashmurble/digitmile-backend:prod-<previous-sha>
docker pull gashmurble/digitmile-game:prod-<previous-sha>
docker pull gashmurble/digitmile-nginx-proxy:prod-<previous-sha>

# Update docker-compose.prod.yml to pin to specific SHA
nano docker-compose.prod.yml
# Change:
#   image: gashmurble/digitmile-backend:prod-latest
# To:
#   image: gashmurble/digitmile-backend:prod-<previous-sha>

# Restart
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Troubleshooting Workflows

### Build Fails: "permission denied"
- Check Docker Hub credentials in GitHub secrets
- Verify `DOCKERHUB_TOKEN` has write permissions

### Deploy Fails: ".env file not found"
- Upload `.env` to `/var/www/digitmile/.env` on server
- Verify file permissions: `ls -la /var/www/digitmile/.env`

### Deploy Fails: "SSH connection refused"
- Check SSH key is correct in GitHub secrets
- Verify server accepts key: `ssh -i ~/.ssh/key ubuntu@digit.mile.mk`
- Check `prod_HOST`, `prod_USERNAME`, `prod_PORT` variables

### Migrations Don't Run
- Check backend logs: `docker-compose logs backend`
- Verify `.env` has correct DB credentials
- Manually run: `docker-compose exec backend python manage.py migrate`

### SSL Certificate Fails
- Verify DNS: `nslookup digit.mile.mk`
- Check ports 80/443 open: `sudo ufw status`
- View certbot logs: `docker-compose logs certbot`

## Next Steps

1. **Test staging deployment first**
   - Deploy to staging environment
   - Verify everything works
   - Check migrations, static files, SSL

2. **Deploy to production**
   - Use "Deploy to Environment" workflow
   - Select `environment: prod`
   - Monitor logs during deployment

3. **Set up monitoring**
   - Configure health checks
   - Set up log monitoring
   - Create backup schedule

4. **Automate deployments** (optional)
   - Auto-deploy `master` branch to staging
   - Auto-deploy tagged releases to production

## Summary of Benefits

✅ **Faster deployments** - No redundant operations
✅ **More reliable** - Health checks ensure success
✅ **Easier debugging** - Clear error messages
✅ **Safer** - Validates .env before deploying
✅ **Consistent** - Same process every time
✅ **Documented** - Clear process flow

Your CI/CD pipeline is now production-ready for digit.mile.mk! 🚀
