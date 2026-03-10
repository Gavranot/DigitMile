# Quick Deployment Reference for digit.mile.mk

## TL;DR - Fast Deployment Commands

### On Your Local Machine (Windows)

```bash
# 1. Create production .env
cp .env.production .env.prod

# 2. Edit .env.prod and change:
#    - DB_PASS (use: openssl rand -base64 32)
#    - SECRET_KEY (use Python or https://djecrety.ir/)
#    - Keep DEBUG=False

# 3. Don't commit secrets!
echo ".env.prod" >> .gitignore

# 4. Upload to server (replace with your server IP)
scp -r * your-user@your-server-ip:/var/www/digitmile/
scp .env.prod your-user@your-server-ip:/var/www/digitmile/.env
```

### On Your Server

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
sudo usermod -aG docker $USER
exit  # Log out and back in

# 2. Go to project directory
cd /var/www/digitmile

# 3. Initialize SSL
chmod +x scripts/init-letsencrypt.sh
./scripts/init-letsencrypt.sh digit.mile.mk admin@digit.mile.mk

# 4. Deploy
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 5. Create superuser
docker-compose exec backend python manage.py createsuperuser

# Done! Visit: https://digit.mile.mk
```

## Pre-Deployment Checklist

Before deploying, ensure:

- [ ] DNS A record: `digit.mile.mk` → your server IP
- [ ] DNS A record: `www.digit.mile.mk` → your server IP (optional)
- [ ] Server ports 80 and 443 are open
- [ ] `.env.prod` created with strong passwords
- [ ] Unity game updated with `https://digit.mile.mk/panel/` URL

## Essential Commands

### Deployment

```bash
# Deploy/Update
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Stop
docker-compose down

# View logs
docker-compose logs -f backend

# Restart single service
docker-compose restart backend
```

### Database

```bash
# Backup
docker-compose exec db pg_dump -U digitmile digitmile | gzip > backup.sql.gz

# Restore
gunzip < backup.sql.gz | docker-compose exec -T db psql -U digitmile digitmile

# Migrations
docker-compose exec backend python manage.py migrate
```

### SSL

```bash
# Renew certificate
docker-compose run --rm certbot renew

# Test renewal
docker-compose run --rm certbot renew --dry-run
```

## Your Production URLs

- **Game:** https://digit.mile.mk
- **Admin:** https://digit.mile.mk/admin/
- **API:** https://digit.mile.mk/panel/api/

## What's Different in Production?

| Setting | Development | Production |
|---------|-------------|------------|
| **Domain** | localhost | digit.mile.mk |
| **Protocol** | HTTP | HTTPS |
| **DEBUG** | True | False |
| **ALLOWED_HOSTS** | * | digit.mile.mk only |
| **SECRET_KEY** | Insecure default | Strong random key |
| **DB Password** | Simple | Strong random |
| **SSL** | Self-signed/none | Let's Encrypt |
| **Ports** | All exposed | Only 80/443 via proxy |

## Configuration Files Updated

✅ `nginx-proxy/nginx.conf.production` - Domain: digit.mile.mk
✅ `.env.production` - Template with your domain
✅ `docker-compose.prod.yml` - Uses root `.env`
✅ `DigitMilePanel/digitmile/settings.py` - Reads from environment

## Need Help?

**Full Guide:** See `PRODUCTION-DEPLOYMENT.md`

**Common Issues:**
- SSL not working? Check DNS with `nslookup digit.mile.mk`
- 502 error? Check backend logs: `docker-compose logs backend`
- DB connection failed? Check `.env` DB_* values match

**Get Support:**
- Logs: `docker-compose logs -f`
- Container status: `docker-compose ps`
- Resource usage: `docker stats`
