from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
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

    yield

    stop_event.set()
    await monitor_task


app = FastAPI(title="Server Rent Alpha", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
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
