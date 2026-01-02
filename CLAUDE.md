# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

DigitMile is a full-stack educational platform combining a Unity WebGL game with a Django REST API backend. The platform enables teachers to create classrooms, track student progress through game statistics, and manage educational content. Schools and teachers must be approved through an admin panel before gaining access.

## Architecture

### Three-Tier System
1. **Unity WebGL Game (Frontend)** - Served via nginx at `/`
2. **Django Backend (API + Admin)** - Served at `/panel/*` and `/admin/*`
3. **PostgreSQL Database** - Primary data store

### Request Flow
```
Client → NGINX Reverse Proxy (SSL termination)
  ├─→ /panel/* → Django Backend (Gunicorn) → PostgreSQL
  ├─→ /admin/* → Django Admin → PostgreSQL
  └─→ /* → Unity Game (static files via nginx)
```

### CSRF Authentication Pattern
Unity game authenticates with Django using a **Fetch-and-Header** pattern:
1. Unity calls `/panel/api/fetchCSRFToken/` to obtain a CSRF token
2. Unity includes token in `X-CSRFToken` header for subsequent API calls
3. Critical for `checkClassroomKey` and `insertLevelStatistics` endpoints

This is implemented in Unity's `DataHandler` class and Django's `FetchCSRFTokenView`.

## Development Commands

### Starting Services

```bash
# Development (HTTP only)
docker-compose up -d

# Development with HTTPS (self-signed cert)
docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d

# Production
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Django Backend

```bash
# Run migrations
docker-compose exec backend python manage.py migrate

# Create superuser (or use auto-create via env vars)
docker-compose exec backend python manage.py createsuperuser

# Access Django shell
docker-compose exec backend python manage.py shell

# Collect static files
docker-compose exec backend python manage.py collectstatic --noinput

# View logs
docker-compose logs -f backend

# Access container shell
docker-compose exec backend sh
```

### Database Operations

```bash
# Access database shell
docker-compose exec backend python manage.py dbshell

# Direct PostgreSQL access
docker-compose exec db psql -U digitmile_user digitmile

# Backup database
docker-compose exec db pg_dump -U digitmile_user digitmile > backup.sql

# Restore database
docker-compose exec -T db psql -U digitmile_user digitmile < backup.sql
```

### Rebuilding Containers

```bash
# Rebuild specific service
docker-compose up -d --build backend

# Rebuild all services
docker-compose up -d --build
```

## Django Project Structure

### Core Apps
- **digitmile/** - Project settings and URL configuration
- **digitmileapi/** - Main API application containing models, views, serializers

### Key Models (digitmileapi/models.py)

**School** - Educational institutions requiring approval
- Status workflow: PENDING → APPROVED/REJECTED
- Cascade behavior: Rejecting a school rejects teachers who have only that school (disables login, preserves data)
- Uses `SchoolManager` for filtered querysets (`School.objects.approved()`)
- REJECTED schools are visible only to superusers

**Teacher** - Instructors linked to one or more schools
- Many-to-many relationship with Schools via `TeacherSchoolAssignment`
- Linked to Django User via `OneToOneField` (created upon approval)
- **Non-destructive rejection**: When rejected, `user.is_active = False` to prevent login while preserving all data
- REJECTED teachers cannot log in and are hidden from all non-superuser views
- All classrooms, students, and run statistics are preserved for audit purposes

**Classroom** - Learning groups within a school
- Belongs to one Teacher and one School
- Identified by unique `classroom_key`
- Validation ensures teacher is assigned to the classroom's school

**Student** - Individual learners in classrooms
- Unique per classroom (same name allowed across different classrooms)
- Tracks basic info: name, DOB, grade

**RunStatistics** - Game play session data
- Captures: level, score, win/loss, correct/wrong moves, time elapsed
- Linked to Student (cascades on deletion)

### URL Structure

All Django routes are prefixed with `/panel/`:
- `/panel/` - Home view
- `/panel/admin/` - Django admin interface
- `/panel/api/` - REST API endpoints
- `/panel/register/school/` - School registration form
- `/panel/register/teacher/` - Teacher registration form
- `/panel/teacher/statistics/` - Teacher statistics dashboard

### API Endpoints

**Public (Unity Game):**
- `POST /panel/api/fetchCSRFToken/` - Get CSRF token for subsequent requests
- `POST /panel/api/checkClassroomKey/` - Validate classroom key and get students
- `POST /panel/api/insertLevelStatistics/` - Submit game statistics

**Authenticated (Teachers):**
- `/panel/api/teacher/students/` - ViewSet for managing students (CRUD)
- `GET /panel/api/teacher/classrooms/` - List teacher's classrooms
- `GET /panel/api/teacher/school/` - Get teacher's school info
- `GET /panel/api/teacher/run-statistics/` - View student game statistics

**Admin Only:**
- `/panel/pending-registrations/` - View pending schools/teachers
- `/panel/approve-school/<id>/` - Approve school
- `/panel/reject-school/<id>/` - Reject school (cascade warning)
- `/panel/approve-teacher/<id>/` - Approve teacher (creates User)
- `/panel/reject-teacher/<id>/` - Reject teacher (cascade warning)

### Middleware

**HealthCheckMiddleware** (digitmileapi/middleware.py:6)
- Intercepts `/health/` requests before ALLOWED_HOSTS validation
- Returns `{"status": "healthy"}` for container health checks
- Prevents 400 Bad Request errors from Kubernetes/Docker probes

### Management Commands

**create_superuser** - Auto-creates admin user from environment variables
- Uses: `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`
- Runs on container startup via `docker-compose.yml:48`

**setup_teachers_group** - Creates "Teachers" permission group

## Environment Configuration

Copy `.env.example` to `.env` in repository root and configure:

**Required Variables:**
- `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT` - PostgreSQL connection
- `SECRET_KEY` - Django secret key (generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- `DEBUG` - Set to `False` in production
- `ALLOWED_HOSTS` - Comma-separated list of allowed domains
- `GOOGLE_MAPS_API_KEY` - For location features

**Auto-Superuser (Optional):**
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`

**Email Configuration:**
- `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`

See `.env.example` for complete list.

## Important Settings

### CSRF Configuration
- `CSRF_TRUSTED_ORIGINS` (digitmile/settings.py:40) - Whitelist for CSRF when behind reverse proxy
- `SECURE_PROXY_SSL_HEADER` (digitmile/settings.py:44) - Trust `X-Forwarded-Proto` header from nginx

### CORS
- `CORS_ALLOW_ALL_ORIGINS=True` (digitmile/settings.py:23) - Open for Unity WebGL
- Uses `django-cors-headers` middleware

### Static Files
- Uses **WhiteNoise** for serving static files in production
- `STATIC_ROOT = BASE_DIR / 'staticfiles'`
- Compressed manifest storage for caching

### URL Routing
- `APPEND_SLASH=False` (digitmile/settings.py:53) - Unity sends exact URLs without trailing slashes

## Common Workflows

### Testing Unity-Django Integration

1. Unity must fetch CSRF token first:
```csharp
POST /panel/api/fetchCSRFToken/
```

2. Include token in subsequent requests:
```csharp
Headers: X-CSRFToken: <token>
POST /panel/api/checkClassroomKey/
Body: {"classroom_key": "ABC123"}
```

### Approving/Rejecting Schools and Teachers

**Approval Process:**
1. Navigate to `/panel/pending-registrations/` (admin only)
2. Click approve/reject buttons
3. Approving a teacher creates a Django User account with random password sent via email
4. Approving a school sends notification email to contact person

**Rejection Process (Non-Destructive):**
- When a teacher is rejected:
  - Sets `teacher.status = 'REJECTED'`
  - Sets `teacher.user.is_active = False` (prevents login)
  - Preserves all classrooms, students, and run statistics
  - Teacher becomes invisible to non-superusers but visible in admin for superusers
- When a school is rejected:
  - Sets `school.status = 'REJECTED'`
  - Cascades to teachers who have ONLY that school (disables their login)
  - Preserves all data for audit purposes
  - School becomes invisible to non-superusers

### Adding Test Data

```python
# Access Django shell
docker-compose exec backend python manage.py shell

# Create approved school
from digitmileapi.models import School
school = School.objects.create(
    name="Test School",
    municipality="Skopje",
    region="Skopje",
    address="123 Test St",
    director_name="Director Name",
    school_email="school@test.com",
    status="APPROVED"
)
```

## Deployment

### CI/CD Pipeline

GitHub Actions workflows in `.github/workflows/`:
- **build.yml** - Builds Docker images and pushes to Docker Hub
- **deploy.yml** - Deploys to production/staging servers via SSH
- **deploy-to-environment.yml** - Manual deployment trigger

Trigger deployment: GitHub → Actions → "Deploy to Environment" → Select environment → Run

### Production Checklist

1. Set `DEBUG=False` in `.env`
2. Configure `ALLOWED_HOSTS` with production domain
3. Set `CSRF_TRUSTED_ORIGINS` to production domain
4. Generate strong `SECRET_KEY`
5. Configure email backend for production
6. Run `collectstatic` before deployment
7. Set up SSL certificates (see `scripts/init-letsencrypt.sh`)

## Container Services

- **backend** (digitmile-backend) - Django on Gunicorn, port 8000
- **frontend** (digitmile-game) - nginx serving Unity build, port 80
- **db** (digitmile-postgres) - PostgreSQL 16, port 5432
- **nginx-proxy** (digitmile-nginx-proxy) - Reverse proxy, ports 80/443

Services communicate via Docker network using service names (e.g., `http://backend:8000`).

## Unity Game Notes

- Game files located in `DigitMile/game/` (WebGL build output)
- Served as static files via nginx
- API communication handled through Unity C# scripts (not in this repo)
- Uses classroom keys as primary authentication mechanism for students

## Data Integrity and Audit Trail

**Non-Destructive Rejection Policy:**
- REJECTED teachers and schools are never deleted from the database
- All associated data (classrooms, students, run statistics) is preserved
- Rejected teachers have `user.is_active = False` to prevent login
- Rejected entities are hidden from non-superusers but visible in admin for superusers
- This ensures complete audit trail and prevents accidental data loss

**Queryset Filtering:**
- Non-superusers: REJECTED teachers and schools are automatically filtered out
- Superusers: Can see all records including REJECTED for audit purposes
- API views enforce `teacher.status == 'APPROVED'` check via `IsTeacher` permission class

## Troubleshooting

### Rejected Teacher Attempting Login
- Rejected teachers have `user.is_active = False` and cannot authenticate
- Django's authentication system blocks inactive users by default
- All teacher-specific views check `teacher_profile.status == 'APPROVED'`

### CSRF Token Errors
- Verify Unity is calling `fetchCSRFToken` before other API calls
- Check `CSRF_TRUSTED_ORIGINS` includes the domain
- Ensure `X-CSRFToken` header is present in Unity requests

### Database Connection Issues
- Wait 10-15 seconds after `docker-compose up` for PostgreSQL to initialize
- Check `DB_HOST=db` in `.env` (not `localhost`)
- Verify database service is healthy: `docker-compose ps db`

### 400 Bad Request on Health Checks
- Health check middleware should intercept before ALLOWED_HOSTS
- Check middleware order in `settings.py:70`
- Verify `HealthCheckMiddleware` is first in the list

### Container-Specific Python Dependencies
Database port parsing (digitmile/settings.py:114-136) handles both numeric and empty `DB_PORT` values to prevent psycopg2 errors when running in containers.
