# .env File Configuration Explained

## The Simplified Setup

We now use **ONE `.env` file** in the **root directory** for everything.

```
DigitMile/
├── .env              ← ONE file, used by everything
├── .env.example      ← Template to copy from
├── docker-compose.yml
└── DigitMilePanel/
    ├── .env.example  ← Deprecated (points to root .env)
    └── manage.py
```

## How Docker Compose Uses .env

### Mechanism 1: Automatic Variable Substitution (Parse Time)

Docker Compose **automatically** reads `.env` from the root directory:

```yaml
# docker-compose.yml
environment:
  POSTGRES_USER: ${DB_USER}  # ← Substituted BEFORE container starts
```

**Process:**
1. Docker Compose reads `docker-compose.yml`
2. Finds `${DB_USER}`
3. Looks for `.env` in the **same directory as docker-compose.yml** (root)
4. Replaces `${DB_USER}` with value from `.env` (e.g., `digitmile`)
5. Starts container with `POSTGRES_USER=digitmile`

**You cannot change this behavior** - Docker Compose always looks for `.env` in the root.

### Mechanism 2: Runtime Environment Variables (Container Runtime)

The `env_file` directive passes variables INTO containers:

```yaml
# docker-compose.yml
backend:
  env_file:
    - .env  # ← File loaded INTO container
```

**Process:**
1. Container starts
2. Docker reads `.env` file
3. Sets environment variables **inside** the container
4. Django code runs `os.getenv('DB_USER')` and gets the value

**You CAN change this path** - it can point to any file.

## Why One .env File is Better

### Before (Confusing)
```
.env                      ← Docker Compose reads this
DigitMilePanel/.env       ← Django reads this
```

**Problems:**
- ❌ Two files with duplicate values
- ❌ Easy to update one and forget the other
- ❌ Confusing which file does what
- ❌ Harder to maintain

### After (Simple)
```
.env                      ← Everyone reads this
```

**Benefits:**
- ✅ Single source of truth
- ✅ Update once, works everywhere
- ✅ Clear and simple
- ✅ Standard Docker Compose pattern

## How It Works Now

### Docker Compose (Parse Time)
```yaml
db:
  environment:
    POSTGRES_USER: ${DB_USER}  # Reads from .env (root)
```

**Happens:** Before container starts
**File:** `.env` (root) - automatic, can't change

### Container Runtime (Django)
```yaml
backend:
  env_file:
    - .env  # Loads .env into container
```

**Happens:** After container starts
**File:** `.env` (root) - we specify this

Django code:
```python
# settings.py
import os
DB_USER = os.getenv('DB_USER')  # Gets value from .env
```

## Setup Instructions

### First Time

```bash
# 1. Copy example to create your .env
cp .env.example .env

# 2. Edit with your values
nano .env

# 3. Start Docker Compose
docker-compose up -d
```

### How Variables Flow

```
.env (root directory)
    ↓
    ├─→ Docker Compose reads ${VARIABLES}
    │   └─→ Substitutes in docker-compose.yml
    │
    └─→ env_file: .env
        └─→ Passed INTO containers
            └─→ Django reads os.getenv('VARIABLES')
```

## Example

**`.env` (root):**
```env
DB_USER=digitmile
DB_PASS=secretpassword
```

**`docker-compose.yml`:**
```yaml
db:
  env_file:
    - .env
  environment:
    POSTGRES_USER: ${DB_USER}  # → becomes "digitmile"
    POSTGRES_PASSWORD: ${DB_PASS}  # → becomes "secretpassword"

backend:
  env_file:
    - .env  # Django reads DB_USER=digitmile inside container
```

**Django `settings.py`:**
```python
import os
DATABASES = {
    'default': {
        'USER': os.getenv('DB_USER'),  # → "digitmile"
        'PASSWORD': os.getenv('DB_PASS'),  # → "secretpassword"
    }
}
```

## Why We Had Two Mechanisms

The confusion came from Docker Compose having **two separate features**:

1. **Variable substitution** (`${VAR}`)
   - Built-in, automatic
   - Always reads `.env` from root
   - Can't be changed

2. **Environment files** (`env_file`)
   - Explicit directive
   - Can point to any file
   - Loads vars into container

Originally, I used:
- `.env` (root) for mechanism 1
- `DigitMilePanel/.env` for mechanism 2

But this was unnecessarily complex! Now we use `.env` (root) for **both**.

## Production Considerations

In production, you might want different approaches:

### Option 1: Keep Root .env (Simple)
```bash
# On server
nano /var/www/digitmile/.env
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Pros:** Simple, consistent with development
**Cons:** All secrets in one file

### Option 2: Environment-Specific Files
```yaml
# docker-compose.prod.yml
backend:
  env_file:
    - .env.production  # Different file for prod
```

**Pros:** Separate dev/prod configs
**Cons:** More files to manage

### Option 3: Platform Secrets (Kubernetes, Cloud)
```yaml
# Don't use env_file in production
backend:
  environment:
    DB_USER: ${DB_USER}  # From platform secrets
```

**Pros:** Most secure, managed by platform
**Cons:** Requires infrastructure setup

## FAQ

### Q: Can I put .env in DigitMilePanel/ directory?
**A:** Yes, but you'd need TWO files:
- `.env` (root) - for Docker Compose variable substitution
- `DigitMilePanel/.env` - for `env_file` directive

This is more complex and unnecessary.

### Q: Why doesn't Docker Compose look in DigitMilePanel/.env automatically?
**A:** Docker Compose always looks in the same directory as `docker-compose.yml`. This is a design decision by Docker, not something we can change.

### Q: Do I need quotes in .env file?
**A:** No! `.env` files use simple KEY=VALUE format:

```env
# Good ✅
DB_USER=digitmile
DB_PASS=my$ecret

# Bad ❌
DB_USER="digitmile"  # Quotes become part of the value!
DB_USER = digitmile  # Spaces break parsing!
```

### Q: Can I use different .env files for dev/staging/prod?
**A:** Yes:

```bash
# Development
cp .env.development .env
docker-compose up

# Production
cp .env.production .env
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up
```

Or use `env_file` arrays:
```yaml
backend:
  env_file:
    - .env
    - .env.production  # Overrides .env values
```

## Summary

| Aspect | Old (Complex) | New (Simple) |
|--------|---------------|--------------|
| **Number of .env files** | 2 | 1 |
| **Location** | Root + DigitMilePanel | Root only |
| **Docker Compose reads** | Root/.env | Root/.env |
| **Containers receive** | DigitMilePanel/.env | Root/.env |
| **Maintenance** | Update 2 files | Update 1 file |
| **Clarity** | Confusing | Clear |

**Bottom line:** One `.env` file in the root directory. Docker Compose reads it automatically for `${VARIABLE}` substitution, and we explicitly pass it to containers via `env_file: .env`. Simple! ✅
