# CI/CD Pipeline Setup Guide

## Overview

The CI/CD pipeline automatically builds Docker images and deploys them to your server when you push to GitHub.

**Workflow:**
1. Push code to GitHub
2. GitHub Actions builds Docker images
3. Images pushed to Docker Hub
4. Server pulls new images and restarts containers
5. Migrations run automatically

## Prerequisites

### 1. Docker Hub Account

Create a free account at https://hub.docker.com

**Create Access Token:**
1. Go to Account Settings → Security
2. Click "New Access Token"
3. Name: "GitHub Actions"
4. Permissions: Read, Write, Delete
5. Copy the token (you'll need it for GitHub secrets)

### 2. Server Requirements

- Ubuntu/Debian server with Docker and Docker Compose installed
- SSH access with key-based authentication
- Ports 80 and 443 open
- Domain pointing to server (for production with SSL)

### 3. GitHub Repository Secrets

Go to your GitHub repo → Settings → Secrets and variables → Actions

**Add these secrets:**

| Secret Name | Description | Example |
|------------|-------------|---------|
| `DOCKERHUB_USERNAME` | Your Docker Hub username | `johndoe` |
| `DOCKERHUB_TOKEN` | Docker Hub access token | `dckr_pat_abc123...` |
| `development_SSH_PRIVATE_KEY` | SSH private key for dev server | `-----BEGIN OPENSSH...` |
| `staging_SSH_PRIVATE_KEY` | SSH private key for staging server | `-----BEGIN OPENSSH...` |
| `prod_SSH_PRIVATE_KEY` | SSH private key for production server | `-----BEGIN OPENSSH...` |

**Add these variables (Settings → Secrets and variables → Actions → Variables):**

| Variable Name | Description | Example |
|--------------|-------------|---------|
| `development_HOST` | Dev server IP/hostname | `dev.digitmile.com` |
| `development_USERNAME` | SSH username for dev | `ubuntu` |
| `development_PORT` | SSH port for dev | `22` |
| `staging_HOST` | Staging server IP/hostname | `staging.digitmile.com` |
| `staging_USERNAME` | SSH username for staging | `ubuntu` |
| `staging_PORT` | SSH port for staging | `22` |
| `prod_HOST` | Production server IP/hostname | `digitmile.com` |
| `prod_USERNAME` | SSH username for production | `ubuntu` |
| `prod_PORT` | SSH port for production | `22` |
| `DOMAIN` | Your production domain | `digitmile.com` |
| `SSL_EMAIL` | Email for Let's Encrypt | `admin@digitmile.com` |

## SSH Key Setup

### Generate SSH Key Pair

On your **local machine**:

```bash
# Generate new SSH key for CI/CD
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/digitmile-deploy

# This creates:
# ~/.ssh/digitmile-deploy (private key - add to GitHub secrets)
# ~/.ssh/digitmile-deploy.pub (public key - add to server)
```

### Add Public Key to Server

On your **server**:

```bash
# Add public key to authorized_keys
cat >> ~/.ssh/authorized_keys << 'EOF'
<paste your digitmile-deploy.pub content here>
EOF

# Set correct permissions
chmod 600 ~/.ssh/authorized_keys
```

### Add Private Key to GitHub

```bash
# Display private key
cat ~/.ssh/digitmile-deploy

# Copy the ENTIRE output (including BEGIN/END lines)
# Add to GitHub Secrets as prod_SSH_PRIVATE_KEY
```

## Server Setup

### 1. Prepare Server Directory

SSH into your server and run:

```bash
# Create deployment directory
sudo mkdir -p /var/www/digitmile
sudo chown $USER:$USER /var/www/digitmile
cd /var/www/digitmile

# Create .env file with secrets
nano DigitMilePanel/.env
```

**DigitMilePanel/.env template:**
```env
# Database
DB_NAME=digitmile
DB_USER=digitmile_user
DB_PASS=<generate-strong-password>
DB_HOST=db
DB_PORT=5432

# Django
DEBUG=False
SECRET_KEY=<generate-strong-secret-key>
ALLOWED_HOSTS=your-domain.com,www.your-domain.com

# Add your API keys and secrets
# API_KEY=...
# EMAIL_HOST_PASSWORD=...
```

**Generate secure secrets:**
```bash
# Generate SECRET_KEY
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# Generate DB_PASS
openssl rand -base64 32
```

### 2. Install Docker (if not installed)

```bash
# Update packages
sudo apt update

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install docker-compose-plugin

# Logout and login again for group changes to take effect
```

## How to Use the CI/CD Pipeline

### Manual Deployment

Go to GitHub → Actions → "Deploy to Environment" → Run workflow

Select:
- **Branch**: `master` (or your branch)
- **Environment**: `development`, `staging`, or `prod`

Click "Run workflow"

### Automatic Deployment (Optional)

To auto-deploy on push, create `.github/workflows/auto-deploy.yml`:

```yaml
name: Auto Deploy

on:
  push:
    branches:
      - master  # Auto-deploy master to staging
      - production  # Auto-deploy production to prod

jobs:
  deploy:
    uses: ./.github/workflows/deploy-to-environment.yml
    with:
      ref: ${{ github.ref }}
      environment: ${{ github.ref == 'refs/heads/production' && 'prod' || 'staging' }}
    secrets: inherit
```

## Deployment Process

When you trigger a deployment:

1. **Build Phase** (3-5 minutes)
   - Checks out code
   - Builds Docker images for game, backend, nginx-proxy
   - Pushes images to Docker Hub

2. **Deploy Phase** (2-3 minutes)
   - Uploads configuration files to server
   - SSHs into server
   - Pulls latest Docker images
   - Stops old containers
   - Starts new containers
   - Runs database migrations
   - Collects static files

3. **SSL Phase** (1-2 minutes, first deploy only)
   - Requests Let's Encrypt certificate
   - Configures NGINX with SSL

**Total time:** ~5-10 minutes for complete deployment

## Monitoring Deployment

### GitHub Actions

- Go to GitHub → Actions
- Click on your workflow run
- Watch real-time logs

### Server Logs

SSH into server and run:

```bash
cd /var/www/digitmile

# View all container logs
docker-compose logs -f

# View specific container
docker-compose logs -f backend
docker-compose logs -f nginx-proxy

# Check container status
docker-compose ps
```

## Troubleshooting

### Build fails: "permission denied"
- Check Docker Hub credentials in GitHub secrets
- Verify DOCKERHUB_TOKEN has write permissions

### Deploy fails: "SSH connection refused"
- Verify server IP/hostname in GitHub variables
- Check SSH key is correct (includes BEGIN/END lines)
- Test SSH: `ssh -i ~/.ssh/digitmile-deploy ubuntu@your-server`

### Containers won't start
- Check .env file exists on server: `/var/www/digitmile/DigitMilePanel/.env`
- View logs: `docker-compose logs backend`
- Check port conflicts: `sudo netstat -tlnp | grep -E '80|443|8000|5432'`

### SSL certificate fails
- Verify domain DNS points to server: `nslookup your-domain.com`
- Check ports 80/443 are open: `sudo ufw status`
- View certbot logs: `docker-compose logs certbot`

### Database migration errors
- Manually run migrations: `docker-compose exec backend python manage.py migrate`
- Check database is running: `docker-compose ps db`
- View DB logs: `docker-compose logs db`

## Rollback

If deployment breaks:

```bash
# SSH into server
cd /var/www/digitmile

# Pull specific version
docker pull username/digitmile-backend:prod-abc123

# Edit docker-compose.yml to pin version
# Change: image: username/digitmile-backend:prod-latest
# To:     image: username/digitmile-backend:prod-abc123

# Restart
docker-compose down
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Best Practices

1. **Test in staging first** - Always deploy to staging before production
2. **Use environment variables** - Never commit secrets to git
3. **Monitor logs** - Check logs after every deployment
4. **Backup database** - Schedule regular backups before deployments
5. **Version your images** - Tags include git SHA for easy rollback

## Next Steps

- [ ] Set up GitHub secrets and variables
- [ ] Configure server with .env file
- [ ] Generate and add SSH keys
- [ ] Run first manual deployment to staging
- [ ] Test staging environment
- [ ] Set up production domain and SSL
- [ ] Deploy to production
- [ ] Set up automated deployments (optional)
