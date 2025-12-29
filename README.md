# DigitMile

Full-stack web application with Unity WebGL game and Django REST API backend.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 NGINX Reverse Proxy                 │
│              (SSL/TLS Termination)                  │
└─────────────────┬───────────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
┌───────▼────────┐  ┌──────▼──────────┐
│  Unity Game    │  │ Django Backend  │
│  (Frontend)    │  │   (API/Admin)   │
│  Port 80       │  │   Port 8000     │
└────────────────┘  └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   PostgreSQL    │
                    │   Database      │
                    └─────────────────┘
```

## Quick Start

### Development (Local)

1. **Copy environment file:**
   ```bash
   cp DigitMilePanel/.env.example DigitMilePanel/.env
   ```

2. **Edit `.env` with your configuration**

3. **Start services:**
   ```bash
   # Without HTTPS (HTTP only)
   docker-compose up -d

   # With HTTPS (self-signed certificate)
   docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d
   ```

4. **Access:**
   - Game: http://localhost (or https://localhost)
   - Backend API: http://localhost/panel/
   - Admin: http://localhost/admin/

### Production (With Domain)

See [CI-CD-SETUP.md](./CI-CD-SETUP.md) for complete deployment guide.

## Project Structure

```
DigitMile/
├── DigitMile/              # Unity WebGL game (static files)
│   ├── game/               # Built Unity game files
│   ├── nginx.conf          # NGINX config for serving game
│   └── Dockerfile          # Game container
│
├── DigitMilePanel/         # Django backend
│   ├── digitmile/          # Django project settings
│   ├── digitmileapi/       # Main API app
│   ├── requirements.txt    # Python dependencies
│   ├── Dockerfile          # Production Dockerfile
│   └── Dockerfile.compose  # Development Dockerfile
│
├── nginx-proxy/            # Reverse proxy (SSL termination)
│   ├── nginx.conf.production   # Production config (Let's Encrypt)
│   ├── nginx.conf.localhost    # Development config (self-signed)
│   └── Dockerfile          # NGINX proxy container
│
├── .github/workflows/      # CI/CD pipelines
│   ├── build.yml           # Build Docker images
│   ├── deploy.yml          # Deploy to servers
│   └── deploy-to-environment.yml  # Manual deployment trigger
│
├── k8s/                    # Kubernetes configurations
│   ├── base/               # Base configurations
│   └── overlays/           # Environment-specific overlays
│
├── scripts/                # Helper scripts
│   ├── init-letsencrypt.sh      # SSL certificate setup
│   └── setup-nginx-config.sh    # NGINX config helper
│
├── docker-compose.yml           # Base compose file
├── docker-compose.localhost.yml # Local dev with SSL
├── docker-compose.prod.yml      # Production overrides
│
└── Documentation:
    ├── README.md           # This file
    ├── CI-CD-SETUP.md      # CI/CD deployment guide
    ├── SSL-SETUP.md        # SSL certificate guide
    └── DEPLOYMENT.md       # Environment variables guide
```

## Services

### Frontend (Unity Game)
- **Container:** `digitmile-game`
- **Image:** nginx:alpine
- **Port:** 80 (internal)
- **Routes:** `/` (all game routes)

### Backend (Django)
- **Container:** `digitmile-backend`
- **Image:** python:3.12-slim
- **Port:** 8000 (internal)
- **Routes:** `/panel/*`, `/admin/*`
- **Tech Stack:**
  - Django 5.2
  - Django REST Framework
  - PostgreSQL (via psycopg2)
  - Gunicorn (WSGI server)
  - WhiteNoise (static files)

### Database
- **Container:** `digitmile-postgres`
- **Image:** postgres:16-alpine
- **Port:** 5432

### NGINX Reverse Proxy
- **Container:** `digitmile-nginx-proxy`
- **Image:** nginx:alpine
- **Ports:** 80 (HTTP), 443 (HTTPS)
- **Purpose:** SSL termination, request routing

## Container Communication

Within Docker network, use service names:

```csharp
// Unity C# - Connect to backend
string apiUrl = "http://backend:8000/panel/";  // Development
string apiUrl = "https://your-domain.com/panel/";  // Production
```

```python
# Django - Connect to database
DATABASES = {
    'default': {
        'HOST': 'db',  # Service name, not IP
        'PORT': 5432,
    }
}
```

## Environment Variables

All secrets are stored in `DigitMilePanel/.env` (NOT committed to git).

**Required variables:**
```env
# Database
DB_NAME=digitmile
DB_USER=digitmile_user
DB_PASS=<your-password>
DB_HOST=db
DB_PORT=5432

# Django
SECRET_KEY=<your-secret-key>
DEBUG=False
ALLOWED_HOSTS=your-domain.com
```

See [DEPLOYMENT.md](./DEPLOYMENT.md) for full environment variable guide.

## SSL/HTTPS Options

### Self-Signed (Development)
```bash
cd nginx-proxy
bash generate-self-signed-cert.sh
docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d
```

### Let's Encrypt (Production)
```bash
./scripts/init-letsencrypt.sh your-domain.com your-email@example.com
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

See [SSL-SETUP.md](./SSL-SETUP.md) for detailed SSL configuration.

## CI/CD Pipeline

Automated build and deployment using GitHub Actions.

**Trigger deployment:**
- Go to GitHub → Actions → "Deploy to Environment"
- Select branch and environment
- Click "Run workflow"

**Workflow:**
1. Build Docker images (game, backend, nginx-proxy)
2. Push to Docker Hub
3. SSH to server
4. Pull latest images
5. Restart containers
6. Run migrations

See [CI-CD-SETUP.md](./CI-CD-SETUP.md) for setup instructions.

## Common Commands

### Development

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend

# Run migrations
docker-compose exec backend python manage.py migrate

# Create superuser
docker-compose exec backend python manage.py createsuperuser

# Access Django shell
docker-compose exec backend python manage.py shell

# Stop services
docker-compose down
```

### Production

```bash
# Deploy latest
docker-compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f

# Backup database
docker-compose exec db pg_dump -U digitmile_user digitmile > backup.sql

# Restore database
docker-compose exec -T db psql -U digitmile_user digitmile < backup.sql
```

## Troubleshooting

### Backend won't start
```bash
# Check logs
docker-compose logs backend

# Common issues:
# - Missing .env file
# - Database not ready (wait a few seconds)
# - Port 8000 already in use
```

### Database connection errors
```bash
# Check database is running
docker-compose ps db

# Test connection
docker-compose exec backend python manage.py dbshell
```

### SSL certificate issues
```bash
# Check certbot logs
docker-compose logs certbot

# Renew certificate manually
docker-compose run --rm certbot renew
docker-compose restart nginx-proxy
```

### Unity game can't reach backend
- Check URL in Unity scripts uses correct hostname
- Verify CORS is enabled (already configured in settings.py)
- Check browser console for errors

## Development Workflow

1. **Make changes to code**
2. **Rebuild containers:**
   ```bash
   docker-compose up -d --build
   ```
3. **Test locally**
4. **Commit to git**
5. **Deploy via GitHub Actions** (or manually)

## Contributing

1. Create a feature branch
2. Make your changes
3. Test locally with `docker-compose up`
4. Push and create Pull Request
5. Deploy to staging for testing
6. Merge and deploy to production

## License

[Your License Here]

## Support

For issues, please check:
- [CI-CD-SETUP.md](./CI-CD-SETUP.md) - Deployment issues
- [SSL-SETUP.md](./SSL-SETUP.md) - SSL/HTTPS issues
- [DEPLOYMENT.md](./DEPLOYMENT.md) - Environment configuration issues
