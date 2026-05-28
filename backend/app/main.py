from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.utils.proxy import proxy_request
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.deployments import router as deployments_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.deployment_service import DeploymentService
from app.services.docker_manager import DockerManager
from app.services.monitor import monitor_deployments
from app.websocket.logs import router as websocket_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    docker_manager = DockerManager()
    deployment_service = DeploymentService(docker_manager)
    await docker_manager.ensure_network()

    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(monitor_deployments(deployment_service, stop_event))
    app.state.docker_manager = docker_manager
    app.state.deployment_service = deployment_service

    async with httpx.AsyncClient() as client:
        app.state.http_client = client
        yield

    stop_event.set()
    await monitor_task


app = FastAPI(
    title="Server Rent Alpha",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        deploy_port = request.cookies.get("deploy_port")
        if deploy_port:
            try:
                port = int(deploy_port)
                path = request.url.path
                return await proxy_request(request, port=port, path=path, deployment=None)
            except Exception:
                pass
    return await http_exception_handler(request, exc)


cors_origins = [settings.frontend_origin]
if settings.frontend_origins:
    cors_origins.extend(origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(cors_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(deployments_router)
app.include_router(websocket_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
