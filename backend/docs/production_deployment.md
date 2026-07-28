# Mama AI Backend Production Deployment

This deployment runs the **Mama AI API control plane** in a hardened Linux
container. Desktop control, camera, microphone, GUI automation, and Windows
application launching remain host-native capabilities. A Linux container cannot
control the Windows desktop that is hosting Docker Desktop.

## Architecture constraints

Mama AI currently uses SQLite plus an in-process durable worker and scheduler.
Production must therefore run exactly **one API process**. Horizontal scaling
requires a later migration to an external database and queue. The deployment
validator rejects `MAMA_DEPLOYMENT_WORKERS` values other than `1`.

Persistent state is separated into named Docker volumes:

- SQLite database
- database backups
- structured logs
- cache
- screenshots
- models

The application container runs as the non-root `mama-ai` user, drops Linux
capabilities, enables `no-new-privileges`, and uses a read-only root filesystem.

## 1. Prepare production configuration

Copy `backend/.env.example` to `backend/.env` locally. Never commit `.env`.
Generate independent random values for:

- `MAMA_AUTH_SIGNING_SECRET`
- `MAMA_AUTH_TWO_FACTOR_SECRET_KEY`
- `GEMINI_API_KEY`

Production settings must include values similar to:

```dotenv
ENVIRONMENT=production
DEBUG=False
MAMA_DEPLOYMENT_VALIDATE_ENV=True
MAMA_DEPLOYMENT_WORKERS=1
MAMA_DEPLOYMENT_ENABLE_DOCS=False
MAMA_DEPLOYMENT_REQUIRE_HTTPS=True
MAMA_CONTAINER_MODE=True
MAMA_STATIC_TOKEN_COMPATIBILITY_ENABLED=False
MAMA_AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED=False
MAMA_AUTH_PUBLIC_BASE_URL=https://api.example.com
MAMA_CORS_ORIGINS=https://app.example.com
MAMA_TRUSTED_HOSTS=api.example.com
MAMA_FORWARDED_ALLOW_IPS=127.0.0.1
```

Do not use wildcard trusted hosts or wildcard CORS in production.

Validate without printing secrets:

```powershell
cd backend
python -m app.deployment.validation
cd ..
```

## 2. Local development container

From the repository root:

```powershell
docker compose -f compose.backend.dev.yaml up --build
```

Development documentation is available at `http://127.0.0.1:8000/docs` when
`MAMA_DEPLOYMENT_ENABLE_DOCS=True`.

## 3. Production build and deployment

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backend_deploy.ps1 -ImageTag 1.0.0
```

The production Compose file binds the API to `127.0.0.1` only. Put Nginx, Caddy,
or a managed TLS load balancer in front of it. An Nginx example is provided at
`deploy/backend/nginx.conf`.

Manual commands:

```powershell
$env:MAMA_IMAGE_TAG = "1.0.0"
docker compose -f compose.backend.yaml config --quiet
docker compose -f compose.backend.yaml build --pull backend
docker compose -f compose.backend.yaml run --rm --no-deps backend python -m app.deployment.validation
docker compose -f compose.backend.yaml up -d backend
python scripts/backend_smoke_test.py --base-url http://127.0.0.1:8000
```

## 4. Release images

Tag immutable images with the Git commit or release number. Do not deploy only a
mutable `latest` tag in a production environment.

```powershell
$commit = git rev-parse --short HEAD
docker build -t ghcr.io/OWNER/mama-ai-backend:$commit backend
docker push ghcr.io/OWNER/mama-ai-backend:$commit
```

Update the Compose image registry reference before using a remote registry.

## 5. Database backup before deployment

Create and verify a backup before any upgrade:

```powershell
docker compose -f compose.backend.yaml exec backend python -m app.database.recovery_cli backup --reason pre_deploy
docker compose -f compose.backend.yaml exec backend python -m app.database.recovery_cli list
```

Database schema migration runs during application startup. Do not start two
versions against the same SQLite volume simultaneously.

## 6. Rollback

Rollback the image only after creating a pre-rollback database backup:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backend_rollback.ps1 -ImageTag PREVIOUS_IMMUTABLE_TAG
```

Application-image rollback does not automatically reverse a database migration.
Use the database recovery runbook when a schema or data restore is required.

## 7. Health and logs

Public probes:

- `/health` — liveness
- `/health/ready` — readiness

Operational endpoints such as metrics and detailed runtime health remain
protected by RBAC.

```powershell
docker compose -f compose.backend.yaml ps
docker compose -f compose.backend.yaml logs --tail=200 backend
python scripts/backend_smoke_test.py --base-url http://127.0.0.1:8000
```

## 8. CI security gates

`.github/workflows/backend-ci.yml` performs:

- Python compilation
- unit and integration tests
- Bandit scanning of security-sensitive backend modules
- dependency vulnerability scanning with `pip-audit`
- Docker Compose validation
- Docker image build validation
- Gitleaks secret scanning

Dependabot monitors Python, Docker, and GitHub Actions dependencies weekly.

## 9. Production checklist

Before release, verify:

1. All complete test suites end with `OK`.
2. `python -m app.deployment.validation` succeeds in the production environment.
3. The container image has an immutable tag.
4. A verified database backup exists.
5. TLS is active at the reverse proxy or load balancer.
6. `MAMA_TRUSTED_HOSTS` and `MAMA_CORS_ORIGINS` contain only real production domains.
7. Static-token compatibility and development token exposure are disabled.
8. `/health/ready` is healthy after deployment.
9. Logs and metrics are collected by the operations platform.
10. The native desktop agent is deployed separately for host automation.
