from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.deployment import Deployment
from app.services.deployment_service import DeploymentService
from app.services.docker_manager import DockerManagerError

logger = structlog.get_logger()


async def monitor_deployments(service: DeploymentService, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Deployment).where(Deployment.container_id.is_not(None)))
                deployments = result.scalars().all()
                for deployment in deployments:
                    try:
                        stats = await service.record_stats(db, deployment)
                        if stats and not stats.running and settings.docker_auto_restart_unhealthy and deployment.container_id:
                            await service.docker.restart_container(deployment.container_id)
                            deployment.restart_count += 1
                            deployment.status = "running"
                            await db.commit()
                        if stats and stats.running:
                            await service.autoscale_if_needed(db, deployment, stats)
                        await service.refresh_instance_health(db, deployment)
                    except DockerManagerError as exc:
                        deployment.status = "crashed"
                        deployment.last_error = str(exc)
                        await db.commit()
        except Exception as exc:
            logger.exception("deployment_monitor_failed", error=str(exc))

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.monitor_interval_seconds)
        except TimeoutError:
            continue
