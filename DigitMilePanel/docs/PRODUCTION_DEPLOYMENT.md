# Production Deployment Guide

## Overview

This guide covers deploying DigitMile with the new prefixed UUID primary keys.

## Pre-Deployment Checklist

- [ ] All model changes committed to git
- [ ] Local testing completed successfully
- [ ] Database backup created (if preserving any data)
- [ ] Unity client updated to send/receive string IDs

---

## Fresh Deployment (Option 1 - Recommended)

Use this when you're okay with clearing all production data.

### Step 1: SSH into Server

```bash
ssh your-user@your-server
cd /path/to/digitmile
```

### Step 2: Stop Services

```bash
docker-compose down
```

### Step 3: Remove Database Volume

```bash
# List volumes to find the postgres volume name
docker volume ls

# Remove the postgres data volume (DELETES ALL DATA!)
docker volume rm digitmile_postgres_data
# Or if different name:
# docker volume rm <your_postgres_volume_name>
```

### Step 4: Pull Latest Code

```bash
git pull origin master
```

### Step 5: Rebuild and Start Services

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Step 6: Run Migrations

```bash
# Create fresh migrations
docker-compose exec backend python manage.py makemigrations

# Apply migrations
docker-compose exec backend python manage.py migrate
```

### Step 7: Create Superuser

```bash
docker-compose exec backend python manage.py createsuperuser
```

### Step 8: (Optional) Seed Test Data

```bash
# Low volume for quick testing
docker-compose exec backend python manage.py seed_database --preset low

# Medium volume for realistic testing
docker-compose exec backend python manage.py seed_database --preset medium
```

### Step 9: Verify Deployment

```bash
# Check container status
docker-compose ps

# Check logs for errors
docker-compose logs -f backend

# Test health endpoint
curl https://your-domain.com/health/
```

---

## ID Format Reference

| Model | Prefix | Length | Example |
|-------|--------|--------|---------|
| School | `sch_` | 16 | `sch_a1b2c3d4e5f6` |
| Teacher | `tch_` | 16 | `tch_f6e5d4c3b2a1` |
| TeacherSchoolAssignment | `tsa_` | 16 | `tsa_1a2b3c4d5e6f` |
| Classroom | `cls_` | 16 | `cls_abc123def456` |
| Student | `stu_` | 16 | `stu_def456abc123` |
| RunStatistics | `rst_` | 16 | `rst_123abc456def` |
| Run | `run_` | 36 | `run_a1b2c3d4e5f6g7h8i9j0...` |
| TurnEvent | `trn_` | 16 | `trn_456def123abc` |
| SpecialTileTrigger | `stt_` | 16 | `stt_789ghi012jkl` |

---

## Unity Client Changes

Unity must send **string IDs** instead of integers:

### Before (Integer IDs)
```json
{
  "student_id": 123,
  "run_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### After (Prefixed String IDs)
```json
{
  "userID": "stu_abc123def456",
  "run": { ... }
}
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/panel/api/checkClassroomKey/` | POST | Returns student IDs as strings |
| `/panel/api/insertRunData/` | POST | Accepts new run payload format |
| `/panel/api/runs/ingest/` | POST | Legacy endpoint (updated for string IDs) |

---

## Troubleshooting

### Migration Errors

If you see migration conflicts:

```bash
# Inside container
docker-compose exec backend bash

# Delete migration files (keep __init__.py)
cd digitmileapi/migrations
rm 0*.py

# Recreate migrations
python manage.py makemigrations
python manage.py migrate
```

### Database Connection Issues

```bash
# Check if database is running
docker-compose ps db

# Check database logs
docker-compose logs db

# Restart database
docker-compose restart db
```

### Container Won't Start

```bash
# Check for build errors
docker-compose logs backend

# Rebuild from scratch
docker-compose down
docker-compose up -d --build --force-recreate
```

### ID Mismatch Errors

If you see errors like "Student with id X does not exist":
- Ensure Unity is sending the full prefixed ID (e.g., `stu_abc123...`)
- Check that the student was created after the migration (has new ID format)

---

## Rollback Procedure

If deployment fails and you need to rollback:

```bash
# Stop services
docker-compose down

# Checkout previous version
git checkout <previous-commit-hash>

# Remove database (if schema incompatible)
docker volume rm digitmile_postgres_data

# Rebuild and migrate
docker-compose up -d --build
docker-compose exec backend python manage.py migrate
```

---

## Monitoring

### Check Logs

```bash
# All services
docker-compose logs -f

# Backend only
docker-compose logs -f backend

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Check Database

```bash
# Access Django shell
docker-compose exec backend python manage.py shell

# Quick checks
>>> from digitmileapi.models import School, Student, Run
>>> School.objects.count()
>>> Student.objects.first().id  # Should show 'stu_...'
>>> Run.objects.first().id  # Should show 'run_...'
```

---

## Useful Commands

```bash
# Collect static files
docker-compose exec backend python manage.py collectstatic --noinput

# Create database backup
docker-compose exec db pg_dump -U digitmile_user digitmile > backup_$(date +%Y%m%d).sql

# Restore database backup
docker-compose exec -T db psql -U digitmile_user digitmile < backup.sql

# Access database shell
docker-compose exec backend python manage.py dbshell

# Run Django shell
docker-compose exec backend python manage.py shell
```
