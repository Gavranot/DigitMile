# Database Setup Guide

## What Changed

I've updated your configuration so that:

1. **PostgreSQL creates a user named `digitmile`** (not `postgres` or `digitmile_user`)
2. **The user has FULL SUPERUSER permissions** (can create tables, insert data, etc.)
3. **Everything reads from your `.env` file** (no more hardcoded values)

## Updated Files

### DigitMilePanel/.env
```env
DB_HOST=db
DB_NAME=digitmile
DB_USER=digitmile        # ← Changed from "postgres"
DB_PASS=Avram2x3y$$
DB_PORT=5432
```

### docker-compose.yml
- **db service**: Now uses `.env` file and creates user `digitmile`
- **backend service**: Now uses `.env` file instead of hardcoded values

## How PostgreSQL User Creation Works

When PostgreSQL container starts for the **first time**, it reads these environment variables:

```yaml
POSTGRES_DB: digitmile        # Creates database "digitmile"
POSTGRES_USER: digitmile      # Creates user "digitmile"
POSTGRES_PASSWORD: Avram2x3y$$  # Sets password
```

**The user created by `POSTGRES_USER` automatically has SUPERUSER privileges**, which means:
- ✅ Can create tables
- ✅ Can insert/update/delete data
- ✅ Can create other users
- ✅ Can grant permissions
- ✅ Full control over the database

## How to Apply Changes

### Option 1: Fresh Start (Recommended - Deletes All Data)

```bash
# Stop all containers
docker-compose down

# Delete the PostgreSQL volume (THIS DELETES ALL DATA!)
docker volume rm digitmile_postgres_data

# Start fresh - PostgreSQL will create the "digitmile" user
docker-compose up -d

# Check logs to verify user creation
docker-compose logs db
```

### Option 2: Keep Existing Data (Create User Manually)

If you have existing data you want to keep:

```bash
# Connect to the PostgreSQL container
docker-compose exec db psql -U postgres -d digitmile

# Inside PostgreSQL shell, run:
CREATE USER digitmile WITH SUPERUSER PASSWORD 'Avram2x3y$$';
GRANT ALL PRIVILEGES ON DATABASE digitmile TO digitmile;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO digitmile;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO digitmile;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO digitmile;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO digitmile;

# Exit PostgreSQL shell
\q

# Restart backend to use new user
docker-compose restart backend
```

## Verify Everything Works

### 1. Check Database User

```bash
# Connect to database as "digitmile" user
docker-compose exec db psql -U digitmile -d digitmile

# You should see a prompt like:
# digitmile=#

# Check your permissions
\du

# You should see "digitmile" with role attributes: Superuser
```

### 2. Check Django Connection

```bash
# Check backend logs
docker-compose logs backend

# Should see successful migrations without errors

# Test database connection
docker-compose exec backend python manage.py dbshell

# Should connect without errors
```

### 3. Run Migrations

```bash
# Apply all Django migrations
docker-compose exec backend python manage.py migrate

# Should see:
# Operations to perform:
#   Apply all migrations: ...
# Running migrations:
#   ...
# No errors should appear
```

## Current Database Configuration

After applying changes, your setup will be:

| Parameter | Value |
|-----------|-------|
| **Database Name** | digitmile |
| **Database User** | digitmile |
| **Password** | Avram2x3y$$ |
| **Host** | db (service name) |
| **Port** | 5432 |
| **Permissions** | SUPERUSER (full access) |

## Connection Strings

### From Django (automatic via .env)
Django automatically reads from `.env`:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'digitmile',
        'USER': 'digitmile',
        'PASSWORD': 'Avram2x3y$$',
        'HOST': 'db',
        'PORT': '5432',
    }
}
```

### From psql command line
```bash
docker-compose exec db psql -U digitmile -d digitmile
```

### From external tools (e.g., pgAdmin, DBeaver)
```
Host: localhost
Port: 5432
Database: digitmile
Username: digitmile
Password: Avram2x3y$$
```

## Security Notes

### For Production

Before deploying to production, update your `.env` with:

```env
# Generate a strong password
DB_PASS=<use-openssl-rand-base64-32>

# Change Django secret key
SECRET_KEY=<use-django-get-random-secret-key>

# Disable debug mode
DEBUG=False

# Set production hosts
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
```

### Generate Secure Passwords

```bash
# Generate database password
openssl rand -base64 32

# Generate Django secret key
docker-compose exec backend python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Troubleshooting

### "role 'digitmile' does not exist"

This means PostgreSQL still has the old user. Solutions:

**Option A:** Delete volume and restart (loses data)
```bash
docker-compose down
docker volume rm digitmile_postgres_data
docker-compose up -d
```

**Option B:** Create user manually (keeps data) - see "Option 2" above

### "permission denied for table"

Grant permissions manually:
```bash
docker-compose exec db psql -U postgres -d digitmile -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO digitmile;"
```

### "could not translate host name 'db'"

Make sure:
1. `DB_HOST=db` in `.env` (not `DB_HOST=localhost`)
2. Backend and db are on same network (they are in `docker-compose.yml`)
3. Both containers are running: `docker-compose ps`

### Backend can't connect to database

Check `.env` file format:
- No spaces around `=`: `DB_USER=digitmile` ✅ (not `DB_USER = digitmile` ❌)
- No quotes: `DB_USER=digitmile` ✅ (not `DB_USER="digitmile"` ❌)
- Correct values match PostgreSQL container

## Summary

✅ **Database user:** `digitmile` (superuser with full permissions)
✅ **Configuration:** Everything in `.env` file
✅ **Permissions:** Can create tables, insert data, and everything else
✅ **Next step:** Run `docker-compose down && docker volume rm digitmile_postgres_data && docker-compose up -d`
