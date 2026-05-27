# Server Rent Alpha Backend

A lightweight FastAPI PaaS backend for deploying Docker images into isolated containers with strict RAM, CPU, and process limits.

## Features

- JWT signup/login and protected routes
- Async PostgreSQL access with SQLAlchemy
- Alembic migrations
- Docker SDK based deployment lifecycle
- Isolated bridge network for managed containers
- Resource controls: `mem_limit`, `nano_cpus`, `pids_limit`
- Security controls: no privileged mode, dropped Linux capabilities, `no-new-privileges`, optional read-only root filesystem
- Deployment logs via REST and live WebSocket streaming
- Docker stats based CPU/RAM/uptime/restart/running-state metrics
- Background container health monitor
- ARM-friendly Docker usage with no x86-specific image assumptions

## Setup

1. Create your environment file:

```bash
cp .env.example .env
```

2. Install dependencies locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Start PostgreSQL:

```bash
docker compose up -d postgres
```

4. Run migrations:

```bash
alembic upgrade head
```

5. Start the API:

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

## Docker Compose

To run the API and database together:

```bash
docker compose up --build
```

The API service mounts `/var/run/docker.sock` so it can manage sibling containers on the host. In production, treat that socket as highly privileged infrastructure access and isolate this API accordingly.

## API Quick Start

Sign up:

```bash
curl -X POST http://localhost:8000/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"strong-password"}'
```

Login:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"strong-password"}'
```

Deploy an image:

```bash
curl -X POST http://localhost:8000/deploy \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"image_name":"nginx:alpine","internal_port":80,"ram_limit":128,"cpu_limit":0.25,"pids_limit":64}'
```

Deploy a custom Dockerfile:

```bash
curl -X POST http://localhost:8000/deploy/dockerfile \
  -H "Authorization: Bearer $TOKEN" \
  -F dockerfile=@Dockerfile \
  -F context_archive=@build-context.zip \
  -F internal_port=8080 \
  -F ram_limit=128 \
  -F cpu_limit=0.25 \
  -F pids_limit=64
```

Use a build context archive when the Dockerfile references local files with `COPY` or `ADD`. The archive can be `.zip`, `.tar`, `.tar.gz`, or `.tgz`; unsafe paths, symlinks, excessive files, and oversized archives are rejected before Docker sees the build context.

The frontend can also package a selected code directory automatically: select the folder containing `Dockerfile`, and it will upload that Dockerfile plus a generated tar build context.

Check shared resource pool capacity:

```bash
curl http://localhost:8000/resource-pool \
  -H "Authorization: Bearer $TOKEN"
```

Run a command in an owned container:

```bash
curl -X POST http://localhost:8000/deployment/1/exec \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"command":"pwd && ls -la","workdir":"/app"}'
```

List, read, edit, and upload files under the configured workspace root:

```bash
curl "http://localhost:8000/deployment/1/files?path=/app" \
  -H "Authorization: Bearer $TOKEN"

curl "http://localhost:8000/deployment/1/file?path=/app/app/main.py" \
  -H "Authorization: Bearer $TOKEN"

curl -X PUT "http://localhost:8000/deployment/1/file" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"path":"/app/README.md","content":"updated"}'
```

Stream logs:

```bash
websocat "ws://localhost:8000/ws/logs/1?token=$TOKEN"
```

## Important Environment Variables

- `DATABASE_URL`: async SQLAlchemy PostgreSQL URL
- `JWT_SECRET`: signing secret for access tokens
- `DOCKER_NETWORK`: isolated bridge network name
- `DOCKER_INTERNAL_PORT`: default internal container port
- `DOCKER_HOST_PORT_START` / `DOCKER_HOST_PORT_END`: host port allocation range
- `DOCKER_READ_ONLY_DEFAULT`: default read-only root filesystem behavior
- `DOCKER_AUTO_RESTART_UNHEALTHY`: whether the monitor should restart stopped containers
- `DOCKER_BUILD_NETWORK`: network mode used for Dockerfile builds, defaults to `bridge` so package installs like `apt-get` and `pip` can work
- `DOCKERFILE_MAX_BYTES`: maximum uploaded Dockerfile size
- `DOCKER_CONTEXT_MAX_BYTES`: maximum uploaded build context archive size
- `DOCKER_CONTEXT_MAX_FILES`: maximum number of files in an uploaded build context archive
- `DOCKERFILE_BUILD_TIMEOUT_SECONDS`: max build time for uploaded Dockerfiles
- `CONTAINER_EXEC_TIMEOUT_SECONDS`: max runtime for dashboard shell commands
- `CONTAINER_EXEC_MAX_OUTPUT_BYTES`: max captured shell output
- `CONTAINER_WORKSPACE_ROOT`: root path for dashboard file access, defaults to `/app`
- `CONTAINER_FILE_MAX_BYTES`: max file read/write/upload size through the dashboard
- `RESOURCE_POOL_MAX_CPU` / `RESOURCE_POOL_MAX_RAM_MB` / `RESOURCE_POOL_MAX_PIDS`: total admin-managed compute pool
- `RESOURCE_POOL_MAX_DEPLOYMENTS`: maximum active deployments across the pool
- `FRONTEND_ORIGIN`: CORS origin

## Architecture

```text
app/
  api/          HTTP routes and auth dependencies
  core/         config, security, logging
  db/           async SQLAlchemy engine/session
  models/       SQLAlchemy models
  schemas/      Pydantic request/response schemas
  services/     Docker and deployment orchestration
  websocket/    live log streaming
  utils/        small shared helpers
```

The service is intentionally single-node today, but the orchestration boundary lives in `app/services/` so a future scheduler or multi-node Docker/Kubernetes driver can replace the local `DockerManager` without rewriting route logic.
