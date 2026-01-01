# Production Deployment Guide for digit.mile.mk

This guide walks you through deploying DigitMile to your production server with SSL certificates.

## Prerequisites

✅ **Domain:** digit.mile.mk (obtained)
✅ **Server:** Ubuntu/Debian server with SSH access
✅ **DNS:** A record pointing digit.mile.mk to your server IP
✅ **Ports:** 80 and 443 open on firewall

## Step-by-Step Deployment

### 1. Prepare Your Server

SSH into your server and install required software:

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Add user to docker group (replace 'ubuntu' with your username)
sudo usermod -aG docker $USER

# Log out and back in for group changes to take effect
exit
```

### 2. Verify DNS is Configured

Check that your domain points to your server:

```bash
# On your local machine or server
nslookup digit.mile.mk
# Should show your server's IP address

# Or use dig
dig +short digit.mile.mk
```

If DNS isn't set up yet:
1. Log in to your domain registrar (where you bought digit.mile.mk)
2. Add an A record:
   - **Type:** A
   - **Name:** @ (or digit.mile.mk)
   - **Value:** Your server's public IP address
   - **TTL:** 3600 (or default)
3. Add www subdomain (optional):
   - **Type:** A
   - **Name:** www
   - **Value:** Your server's public IP address

DNS changes can take 5-60 minutes to propagate.

### 3. Prepare Local Files for Production

On your **local machine** (Windows), update configuration:

#### A. Generate Secure Credentials

```bash
# Generate secure database password
openssl rand -base64 32

# Copy the output and save it - you'll need it for .env
```

#### B. Create Production .env File

Copy the template:

```bash
cd C:\Users\damja\OneDrive\Documents\Personal\DigitMile
cp .env.production .env.prod
```

Edit `.env.prod` with a text editor and update these values:

```env
# Database Configuration
DB_HOST=db
DB_NAME=digitmile
DB_USER=digitmile
DB_PASS=<paste-your-generated-password-here>
DB_PORT=5432

# Django Configuration
DEBUG=False
SECRET_KEY=<generate-new-secret-key>
SERVER_IP=digit.mile.mk
ALLOWED_HOSTS=digit.mile.mk,www.digit.mile.mk

# API Keys (keep your existing ones)
GOOGLE_MAPS_API_KEY=AIzaSyD8M4oWzr2MC6PEsaOQQb8rA6RtpAQhDKs

# Email Configuration (keep your existing ones)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreplydigitmile@gmail.com
EMAIL_HOST_PASSWORD=vstmfndeoasebrss
DEFAULT_FROM_EMAIL=noreplydigitmile@gmail.com
SITE_URL=https://digit.mile.mk
```

**Generate Django SECRET_KEY:**

```bash
# Option 1: Use Python on Windows
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Option 2: Use online generator
# Visit: https://djecrety.ir/
```

### 4. Upload Files to Server

#### Option A: Using Git (Recommended)

```bash
# On your local machine
cd C:\Users\damja\OneDrive\Documents\Personal\DigitMile

# Ensure .env.prod is in .gitignore (don't commit secrets!)
echo ".env.prod" >> .gitignore

# Commit your code
git add .
git commit -m "Configure for production deployment"
git push origin master

# On your server
ssh your-username@your-server-ip

# Clone repository
cd /var/www
sudo mkdir -p digitmile
sudo chown $USER:$USER digitmile
cd digitmile
git clone <your-repo-url> .
```

Then manually upload `.env.prod` using SCP:

```bash
# On your local machine (Git Bash or PowerShell)
scp .env.prod your-username@your-server-ip:/var/www/digitmile/.env
```

#### Option B: Using SCP (Direct Upload)

```bash
# On your local machine (Git Bash or PowerShell)
# Create directory on server first
ssh your-username@your-server-ip "sudo mkdir -p /var/www/digitmile && sudo chown $USER:$USER /var/www/digitmile"

# Upload entire project
scp -r C:/Users/damja/OneDrive/Documents/Personal/DigitMile/* your-username@your-server-ip:/var/www/digitmile/

# Upload .env.prod as .env
scp .env.prod your-username@your-server-ip:/var/www/digitmile/.env
```

### 5. Initialize SSL Certificates

On your **server**:

```bash
cd /var/www/digitmile

# Make script executable
chmod +x scripts/init-letsencrypt.sh

# Initialize Let's Encrypt certificates
./scripts/init-letsencrypt.sh digit.mile.mk admin@digit.mile.mk

# The script will:
# - Download TLS parameters
# - Update nginx config with your domain
# - Request SSL certificate from Let's Encrypt
# - Configure automatic renewal
```

**If you see an error**, check:
- DNS is properly configured: `nslookup digit.mile.mk`
- Ports 80/443 are open: `sudo ufw status`
- NGINX is running: `docker-compose ps`

### 6. Deploy with Docker Compose

```bash
cd /var/www/digitmile

# Create required directories
mkdir -p certbot/conf certbot/www

# Start services in production mode
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Watch logs to monitor startup
docker-compose logs -f
```

**Wait for:**
- PostgreSQL to initialize
- Backend migrations to complete
- SSL certificates to be issued
- All services to show "Started"

Press `Ctrl+C` to exit logs (containers keep running).

### 7. Verify Deployment

#### Check Services Are Running

```bash
docker-compose ps

# Should show:
# - digitmile-nginx-proxy (running, ports 80->80, 443->443)
# - digitmile-backend (running)
# - digitmile-game (running)
# - digitmile-postgres (running)
# - digitmile-certbot (running)
```

#### Test in Browser

1. **HTTP → HTTPS Redirect:**
   - Visit: http://digit.mile.mk
   - Should redirect to: https://digit.mile.mk

2. **Game (Frontend):**
   - Visit: https://digit.mile.mk
   - Should load Unity game

3. **Admin Panel:**
   - Visit: https://digit.mile.mk/admin/
   - Should show Django admin login (with valid SSL certificate)

4. **API:**
   - Visit: https://digit.mile.mk/panel/api/
   - Should show Django REST Framework browsable API

#### Check SSL Certificate

```bash
# Check certificate details
echo | openssl s_client -servername digit.mile.mk -connect digit.mile.mk:443 2>/dev/null | openssl x509 -noout -dates

# Should show:
# notBefore: <today's date>
# notAfter: <90 days from now>
```

Browser should show:
- ✅ Green padlock icon
- ✅ "Connection is secure"
- ✅ Certificate issued by "Let's Encrypt"

### 8. Create Django Superuser

Create an admin account to access the Django admin:

```bash
docker-compose exec backend python manage.py createsuperuser

# Follow prompts:
# Username: admin
# Email: your-email@example.com
# Password: <strong-password>
```

Test login at: https://digit.mile.mk/admin/

### 9. Update Unity Game Backend URL

In your Unity project, update the backend URL in your C# scripts:

```csharp
// Before (development)
private const string API_URL = "http://backend:8000/panel/";

// After (production)
private const string API_URL = "https://digit.mile.mk/panel/";
```

Rebuild your Unity WebGL game and redeploy the `frontend` container.

## Post-Deployment Configuration

### Setup Automatic Certificate Renewal

Let's Encrypt certificates expire every 90 days. The `certbot` container automatically renews them.

Verify renewal works:

```bash
# Test renewal (dry run)
docker-compose run --rm certbot renew --dry-run

# Should show: "Congratulations, all simulated renewals succeeded"
```

The renewal process runs automatically every 12 hours.

### Configure Firewall

```bash
# If using UFW (Ubuntu Firewall)
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP (for Let's Encrypt challenges)
sudo ufw allow 443/tcp  # HTTPS
sudo ufw enable
sudo ufw status
```

### Setup Automatic Restart on Reboot

```bash
# Add Docker Compose to systemd
sudo tee /etc/systemd/system/digitmile.service > /dev/null <<EOF
[Unit]
Description=DigitMile Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/var/www/digitmile
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

# Enable service
sudo systemctl enable digitmile.service

# Test restart
sudo systemctl restart digitmile.service
sudo systemctl status digitmile.service
```

### Setup Database Backups

```bash
# Create backup script
sudo tee /usr/local/bin/backup-digitmile-db.sh > /dev/null <<'EOF'
#!/bin/bash
BACKUP_DIR="/var/backups/digitmile"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR
cd /var/www/digitmile

docker-compose exec -T db pg_dump -U digitmile digitmile | gzip > $BACKUP_DIR/digitmile_$DATE.sql.gz

# Keep only last 7 days of backups
find $BACKUP_DIR -name "digitmile_*.sql.gz" -mtime +7 -delete

echo "Backup completed: digitmile_$DATE.sql.gz"
EOF

sudo chmod +x /usr/local/bin/backup-digitmile-db.sh

# Add to crontab (daily at 2am)
sudo crontab -e

# Add this line:
0 2 * * * /usr/local/bin/backup-digitmile-db.sh >> /var/log/digitmile-backup.log 2>&1
```

**To restore a backup:**

```bash
# List backups
ls -lh /var/backups/digitmile/

# Restore specific backup
gunzip < /var/backups/digitmile/digitmile_YYYYMMDD_HHMMSS.sql.gz | docker-compose exec -T db psql -U digitmile digitmile
```

## Monitoring & Maintenance

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f nginx-proxy
docker-compose logs -f db

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Update Application

```bash
cd /var/www/digitmile

# Pull latest code
git pull origin master

# Rebuild and restart
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Run migrations
docker-compose exec backend python manage.py migrate

# Collect static files
docker-compose exec backend python manage.py collectstatic --noinput
```

### Check Resource Usage

```bash
# Container resource usage
docker stats

# Disk usage
docker system df

# Clean up unused images/volumes
docker system prune -a --volumes
```

## Troubleshooting

### SSL Certificate Errors

**Problem:** Certificate not working or expired

```bash
# Check certificate
docker-compose logs certbot

# Manually renew
docker-compose run --rm certbot renew

# Restart nginx
docker-compose restart nginx-proxy
```

### Backend Not Responding

**Problem:** API returns 502 Bad Gateway

```bash
# Check backend logs
docker-compose logs backend

# Common issues:
# - Database connection errors (check .env DB_* values)
# - Migration errors (run: docker-compose exec backend python manage.py migrate)
# - Static files missing (run: docker-compose exec backend python manage.py collectstatic --noinput)

# Restart backend
docker-compose restart backend
```

### Database Connection Errors

**Problem:** `connection to server at "db" failed`

```bash
# Check database is running
docker-compose ps db

# Check database logs
docker-compose logs db

# Test connection
docker-compose exec backend python manage.py dbshell

# Restart database (WARNING: make backup first!)
docker-compose restart db
```

### Out of Disk Space

```bash
# Check disk usage
df -h

# Clean up Docker
docker system prune -a --volumes

# Check log files
sudo du -sh /var/lib/docker/
```

## Security Checklist

After deployment, verify:

- ✅ **DEBUG=False** in production .env
- ✅ **Strong SECRET_KEY** generated
- ✅ **Strong DB_PASS** generated
- ✅ **SSL certificate** valid and auto-renewing
- ✅ **Firewall configured** (only ports 22, 80, 443 open)
- ✅ **.env file** not committed to git
- ✅ **Database backups** configured
- ✅ **HTTPS redirect** working
- ✅ **ALLOWED_HOSTS** set to your domain only

## Your Production URLs

| Service | URL |
|---------|-----|
| **Game** | https://digit.mile.mk |
| **Admin Panel** | https://digit.mile.mk/admin/ |
| **API Root** | https://digit.mile.mk/panel/api/ |
| **School Registration** | https://digit.mile.mk/panel/register/school/ |
| **Teacher Registration** | https://digit.mile.mk/panel/register/teacher/ |

## Summary

You now have:

✅ DigitMile running at **https://digit.mile.mk**
✅ SSL certificate from Let's Encrypt (auto-renews)
✅ NGINX reverse proxy routing requests
✅ PostgreSQL database with backups
✅ Docker containers managed by systemd
✅ Firewall configured
✅ Production-ready Django settings

**Your app is live!** 🎉

For ongoing updates, use Git to push changes and rebuild containers. For help, check the logs with `docker-compose logs -f`.
