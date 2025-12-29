# Deployment Guide

## How Environment Variables Work

### Development (Local)
- Uses `docker-compose.yml`
- Reads from `DigitMilePanel/.env` file
- `.env` is **NOT** copied into Docker image (blocked by `.dockerignore`)
- Django's `python-dotenv` loads variables from mounted `.env` file

### Production
- `.env` file does NOT exist in the image (security best practice)
- Environment variables are injected by your orchestration platform
- Django falls back to reading from environment variables directly
- `python-dotenv` gracefully handles missing `.env` file

## Production Deployment Options

### Option 1: Kubernetes (Recommended for Scale)

```yaml
# k8s/backend-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: backend-secrets
type: Opaque
stringData:
  DB_PASS: your-database-password
  SECRET_KEY: your-django-secret-key
  API_KEY: your-api-key
  # Add all your secrets here

---
# k8s/backend-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
spec:
  template:
    spec:
      containers:
      - name: backend
        image: your-registry/digitmile-backend:latest
        env:
          # Non-secret config
          - name: DB_HOST
            value: "postgres-service"
          - name: DB_PORT
            value: "5432"
          - name: DEBUG
            value: "False"
          # Secrets from Secret object
          - name: DB_PASS
            valueFrom:
              secretKeyRef:
                name: backend-secrets
                key: DB_PASS
          - name: SECRET_KEY
            valueFrom:
              secretKeyRef:
                name: backend-secrets
                key: SECRET_KEY
```

### Option 2: Docker Swarm

```bash
# Create secrets
echo "your-db-password" | docker secret create db_password -
echo "your-secret-key" | docker secret create django_secret -

# Deploy stack
docker stack deploy -c docker-compose.yml -c docker-compose.prod.yml digitmile
```

### Option 3: Cloud Platform Environment Variables

**AWS ECS/Fargate:**
- Use AWS Secrets Manager or Systems Manager Parameter Store
- Reference secrets in task definition

**Google Cloud Run:**
```bash
gcloud run deploy backend \
  --image gcr.io/your-project/backend \
  --set-env-vars DB_HOST=your-db \
  --set-secrets DB_PASS=db-password:latest
```

**Azure Container Instances:**
```bash
az container create \
  --name backend \
  --image your-registry/backend \
  --environment-variables DB_HOST=your-db \
  --secure-environment-variables DB_PASS=your-password
```

### Option 4: Mount .env as External Volume (Simple but less secure)

```yaml
# docker-compose.prod.yml
services:
  backend:
    volumes:
      # Mount .env from outside the container
      - /secure/path/on/host/.env:/app/.env:ro
```

## Security Best Practices

1. **Never commit `.env` to version control**
   - Already in `.gitignore`
   - Already in `.dockerignore`

2. **Use different secrets per environment**
   - Development: `DigitMilePanel/.env`
   - Staging: Kubernetes secrets / Cloud secrets
   - Production: Kubernetes secrets / Cloud secrets

3. **Rotate secrets regularly**
   - Database passwords
   - API keys
   - Django SECRET_KEY

4. **Limit secret access**
   - Use RBAC in Kubernetes
   - Use IAM roles in cloud platforms
   - Never log secret values

## How It Works

Django's settings.py loads variables in this order:
1. Try to load from `.env` file (if it exists)
2. Fall back to environment variables
3. Use default values (if specified)

```python
# This works in both dev and production
DB_HOST = os.getenv('DB_HOST')  # From .env in dev, from env vars in prod
```

## Testing Production Configuration Locally

```bash
# Test without .env file
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up

# Set required variables first
export DB_NAME=digitmile
export DB_USER=digitmile_user
export DB_PASS=password
export SECRET_KEY=your-secret-key
# ... etc
```

## Current Setup

- **Development**: `docker-compose.yml` uses `DigitMilePanel/.env`
- **Production**: See `docker-compose.prod.yml` for override example
- **Images**: `.env` is excluded via `.dockerignore` (secure by default)
