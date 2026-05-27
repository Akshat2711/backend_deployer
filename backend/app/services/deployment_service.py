from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.deployment import Deployment
from app.models.usage_stats import UsageStats
from app.schemas.deployment import DeploymentCreate
from app.services.docker_manager import DockerManager, DockerManagerError
from app.utils.ports import random_available_port


ACTIVE_RESOURCE_STATUSES = {"building", "pulling", "creating", "starting", "running", "restarting"}
SAFE_DOCKERFILE_INSTRUCTIONS = {
    "ADD",
    "ARG",
    "CMD",
    "COPY",
    "ENTRYPOINT",
    "ENV",
    "EXPOSE",
    "FROM",
    "HEALTHCHECK",
    "LABEL",
    "RUN",
    "SHELL",
    "STOPSIGNAL",
    "USER",
    "VOLUME",
    "WORKDIR",
}


class DeploymentService:
    def __init__(self, docker_manager: DockerManager) -> None:
        self.docker = docker_manager
        self._capacity_lock = asyncio.Lock()

    async def create_deployment(self, db: AsyncSession, *, user_id: int, payload: DeploymentCreate) -> Deployment:
        async with self._capacity_lock:
            await self.ensure_pool_capacity(db, payload=payload)
            assigned_port = random_available_port(settings.docker_host_port_start, settings.docker_host_port_end)
            read_only = settings.docker_read_only_default if payload.read_only is None else payload.read_only
            deployment = Deployment(
                user_id=user_id,
                image_name=payload.image_name,
                status="pulling",
                cpu_limit=payload.cpu_limit,
                ram_limit=payload.ram_limit,
                storage_limit_mb=payload.storage_limit_mb,
                pids_limit=payload.pids_limit,
                scale_mode=payload.scale_mode,
                desired_instances=payload.desired_instances,
                assigned_port=assigned_port,
                internal_port=payload.internal_port,
                read_only=read_only,
            )
            db.add(deployment)
            await db.commit()
            await db.refresh(deployment)

        instance_count = 1 if payload.scale_mode == "auto" else payload.desired_instances
        container_ids: list[str] = []
        assigned_ports: list[int] = []

        try:
            await self.docker.pull_image(payload.image_name)
            deployment.status = "creating"
            await db.commit()

            for instance_index in range(instance_count):
                host_port = random_available_port(settings.docker_host_port_start, settings.docker_host_port_end)
                assigned_ports.append(host_port)
                container_id = await self.docker.create_container(
                    image_name=payload.image_name,
                    host_port=host_port,
                    internal_port=payload.internal_port,
                    cpu_limit=payload.cpu_limit,
                    ram_limit_mb=payload.ram_limit,
                    storage_limit_mb=payload.storage_limit_mb,
                    pids_limit=payload.pids_limit,
                    read_only=read_only,
                    name=f"paas-{deployment.id}-{instance_index + 1}",
                )
                container_ids.append(container_id)

            deployment.container_id = container_ids[0]
            deployment.container_ids = container_ids
            deployment.assigned_ports = assigned_ports
            deployment.assigned_port = assigned_ports[0]
            deployment.status = "starting"
            await db.commit()

            for container_id in container_ids:
                await self.docker.start_container(container_id)

            deployment.status = "running"
            deployment.last_error = None
        except (DockerManagerError, RuntimeError) as exc:
            deployment.status = "failed"
            deployment.last_error = str(exc)
            await db.commit()
            for container_id in container_ids:
                await self.docker.remove_container(container_id, force=True)
            raise

        await db.commit()
        await db.refresh(deployment)
        return deployment

    async def create_dockerfile_deployment(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        payload: DeploymentCreate,
        dockerfile: str,
        context_archive: bytes | None = None,
        context_filename: str | None = None,
    ) -> Deployment:
        self.validate_dockerfile(dockerfile)
        async with self._capacity_lock:
            await self.ensure_pool_capacity(db, payload=payload)
            assigned_port = random_available_port(settings.docker_host_port_start, settings.docker_host_port_end)
            read_only = settings.docker_read_only_default if payload.read_only is None else payload.read_only
            image_tag = f"server-rent-alpha/user-{user_id}-deployment-pending"
            deployment = Deployment(
                user_id=user_id,
                image_name=image_tag,
                status="building",
                cpu_limit=payload.cpu_limit,
                ram_limit=payload.ram_limit,
                storage_limit_mb=payload.storage_limit_mb,
                pids_limit=payload.pids_limit,
                scale_mode=payload.scale_mode,
                desired_instances=payload.desired_instances,
                assigned_port=assigned_port,
                internal_port=payload.internal_port,
                read_only=read_only,
            )
            db.add(deployment)
            await db.commit()
            await db.refresh(deployment)

        image_tag = f"server-rent-alpha/user-{user_id}-deployment-{deployment.id}:latest"
        deployment.image_name = image_tag
        await db.commit()

        instance_count = 1 if payload.scale_mode == "auto" else payload.desired_instances
        container_ids: list[str] = []
        assigned_ports: list[int] = []

        try:
            await self.docker.build_image_from_dockerfile(
                dockerfile=dockerfile,
                tag=image_tag,
                context_archive=context_archive,
                context_filename=context_filename,
            )
            deployment.status = "creating"
            await db.commit()

            for instance_index in range(instance_count):
                host_port = random_available_port(settings.docker_host_port_start, settings.docker_host_port_end)
                assigned_ports.append(host_port)
                container_id = await self.docker.create_container(
                    image_name=image_tag,
                    host_port=host_port,
                    internal_port=payload.internal_port,
                    cpu_limit=payload.cpu_limit,
                    ram_limit_mb=payload.ram_limit,
                    storage_limit_mb=payload.storage_limit_mb,
                    pids_limit=payload.pids_limit,
                    read_only=read_only,
                    name=f"paas-{deployment.id}-{instance_index + 1}",
                )
                container_ids.append(container_id)

            deployment.container_id = container_ids[0]
            deployment.container_ids = container_ids
            deployment.assigned_ports = assigned_ports
            deployment.assigned_port = assigned_ports[0]
            deployment.status = "starting"
            await db.commit()

            for container_id in container_ids:
                await self.docker.start_container(container_id)

            deployment.status = "running"
            deployment.last_error = None
        except (DockerManagerError, RuntimeError) as exc:
            deployment.status = "failed"
            deployment.last_error = str(exc)
            await db.commit()
            for container_id in container_ids:
                await self.docker.remove_container(container_id, force=True)
            raise

        await db.commit()
        await db.refresh(deployment)
        return deployment

    async def get_owned_deployment(self, db: AsyncSession, *, user_id: int, deployment_id: int) -> Deployment | None:
        result = await db.execute(select(Deployment).where(Deployment.id == deployment_id, Deployment.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_public_deployment(self, db: AsyncSession, *, deployment_id: int) -> Deployment | None:
        result = await db.execute(select(Deployment).where(Deployment.id == deployment_id))
        return result.scalar_one_or_none()

    async def choose_route_port(self, deployment: Deployment) -> int:
        container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
        assigned_ports = [int(port) for port in (deployment.assigned_ports or ([deployment.assigned_port] if deployment.assigned_port else []))]

        if deployment.status != "running" or not container_ids or not assigned_ports:
            raise RuntimeError("Deployment has no running instances available")

        pairs = list(zip(container_ids, assigned_ports))
        scored_ports: list[tuple[float, int]] = []
        for container_id, port in pairs:
            try:
                stats = await self.docker.get_stats(container_id)
            except DockerManagerError:
                continue
            if not stats["running"]:
                continue
            ram_limit = int(stats["ram_limit_bytes"]) or 1
            ram_percent = (int(stats["ram_usage_bytes"]) / ram_limit) * 100
            score = float(stats["cpu_usage_percent"]) + ram_percent
            scored_ports.append((score, port))

        if scored_ports:
            return min(scored_ports, key=lambda item: item[0])[1]

        return assigned_ports[0]

    async def resource_pool(self, db: AsyncSession) -> dict[str, float | int]:
        result = await db.execute(
            select(
                Deployment.cpu_limit,
                Deployment.ram_limit,
                Deployment.storage_limit_mb,
                Deployment.pids_limit,
                Deployment.desired_instances,
                Deployment.scale_mode,
                Deployment.container_ids,
            ).where(Deployment.status.in_(ACTIVE_RESOURCE_STATUSES))
        )
        used_cpu = 0.0
        used_ram = 0
        used_storage = 0
        used_pids = 0
        active_deployments = 0

        for cpu_limit, ram_limit, storage_limit, pids_limit, desired_instances, scale_mode, container_ids in result.all():
            running_instances = len(container_ids or [])
            instance_count = running_instances or (desired_instances if scale_mode == "manual" else 1)
            used_cpu += float(cpu_limit) * instance_count
            used_ram += int(ram_limit) * instance_count
            used_storage += int(storage_limit) * instance_count
            used_pids += int(pids_limit) * instance_count
            active_deployments += 1

        return {
            "max_cpu": settings.resource_pool_max_cpu,
            "used_cpu": used_cpu,
            "available_cpu": max(0.0, settings.resource_pool_max_cpu - used_cpu),
            "max_ram_mb": settings.resource_pool_max_ram_mb,
            "used_ram_mb": used_ram,
            "available_ram_mb": max(0, settings.resource_pool_max_ram_mb - used_ram),
            "max_storage_mb": settings.resource_pool_max_storage_mb,
            "used_storage_mb": used_storage,
            "available_storage_mb": max(0, settings.resource_pool_max_storage_mb - used_storage),
            "max_pids": settings.resource_pool_max_pids,
            "used_pids": used_pids,
            "available_pids": max(0, settings.resource_pool_max_pids - used_pids),
            "max_deployments": settings.resource_pool_max_deployments,
            "active_deployments": active_deployments,
        }

    async def ensure_pool_capacity(self, db: AsyncSession, *, payload: DeploymentCreate) -> None:
        pool = await self.resource_pool(db)
        problems: list[str] = []
        instance_count = payload.desired_instances if payload.scale_mode == "manual" else 1
        if int(pool["active_deployments"]) + 1 > settings.resource_pool_max_deployments:
            problems.append("deployment slots")
        if float(pool["used_cpu"]) + payload.cpu_limit * instance_count > settings.resource_pool_max_cpu:
            problems.append("CPU")
        if int(pool["used_ram_mb"]) + payload.ram_limit * instance_count > settings.resource_pool_max_ram_mb:
            problems.append("RAM")
        if int(pool["used_storage_mb"]) + payload.storage_limit_mb * instance_count > settings.resource_pool_max_storage_mb:
            problems.append("storage")
        if int(pool["used_pids"]) + payload.pids_limit * instance_count > settings.resource_pool_max_pids:
            problems.append("PID limit")

        if problems:
            raise RuntimeError(
                "Resource pool capacity exceeded for "
                + ", ".join(problems)
                + f". Available: {pool['available_cpu']} CPU, {pool['available_ram_mb']} MB RAM, {pool['available_storage_mb']} MB storage, {pool['available_pids']} PIDs."
            )

    async def autoscale_if_needed(self, db: AsyncSession, deployment: Deployment, stats: UsageStats) -> bool:
        if deployment.scale_mode != "auto" or deployment.status != "running":
            return False
        if stats.cpu_usage_percent < settings.autoscale_cpu_threshold_percent:
            return False

        container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
        assigned_ports = [int(port) for port in (deployment.assigned_ports or ([deployment.assigned_port] if deployment.assigned_port else []))]
        if len(container_ids) >= settings.resource_pool_max_instances_per_deployment:
            return False

        pool = await self.resource_pool(db)
        if float(pool["used_cpu"]) + deployment.cpu_limit > settings.resource_pool_max_cpu:
            return False
        if int(pool["used_ram_mb"]) + deployment.ram_limit > settings.resource_pool_max_ram_mb:
            return False
        if int(pool["used_storage_mb"]) + deployment.storage_limit_mb > settings.resource_pool_max_storage_mb:
            return False
        if int(pool["used_pids"]) + deployment.pids_limit > settings.resource_pool_max_pids:
            return False

        host_port = random_available_port(settings.docker_host_port_start, settings.docker_host_port_end)
        replica_number = len(container_ids) + 1
        container_id = await self.docker.create_container(
            image_name=deployment.image_name,
            host_port=host_port,
            internal_port=deployment.internal_port,
            cpu_limit=deployment.cpu_limit,
            ram_limit_mb=deployment.ram_limit,
            storage_limit_mb=deployment.storage_limit_mb,
            pids_limit=deployment.pids_limit,
            read_only=deployment.read_only,
            name=f"paas-{deployment.id}-{replica_number}",
        )
        try:
            await self.docker.start_container(container_id)
        except DockerManagerError:
            await self.docker.remove_container(container_id, force=True)
            raise

        container_ids.append(container_id)
        assigned_ports.append(host_port)
        deployment.container_id = container_ids[0]
        deployment.container_ids = container_ids
        deployment.assigned_port = assigned_ports[0]
        deployment.assigned_ports = assigned_ports
        deployment.desired_instances = len(container_ids)
        deployment.last_error = None
        await db.commit()
        return True

    async def record_stats(self, db: AsyncSession, deployment: Deployment) -> UsageStats | None:
        if not deployment.container_id:
            return None
        stats = await self.docker.get_stats(deployment.container_id)
        result = await db.execute(
            select(UsageStats)
            .where(UsageStats.deployment_id == deployment.id)
            .order_by(UsageStats.created_at.desc(), UsageStats.id.desc())
            .limit(1)
        )
        usage = result.scalar_one_or_none()
        if usage is None:
            usage = UsageStats(deployment_id=deployment.id)
            db.add(usage)
            await db.flush()

        usage.cpu_usage_percent = stats["cpu_usage_percent"]
        usage.ram_usage_bytes = stats["ram_usage_bytes"]
        usage.ram_limit_bytes = stats["ram_limit_bytes"]
        usage.uptime_seconds = stats["uptime_seconds"]
        usage.restart_count = stats["restart_count"]
        usage.running = stats["running"]
        usage.created_at = datetime.now(timezone.utc)

        deployment.status = "running" if stats["running"] else stats["status"]
        deployment.restart_count = stats["restart_count"]
        await db.execute(delete(UsageStats).where(UsageStats.deployment_id == deployment.id, UsageStats.id != usage.id))
        await db.commit()
        await db.refresh(usage)
        return usage

    def validate_dockerfile(self, dockerfile: str) -> None:
        encoded = dockerfile.encode("utf-8")
        if len(encoded) > settings.dockerfile_max_bytes:
            raise RuntimeError(f"Dockerfile exceeds {settings.dockerfile_max_bytes} byte limit")
        if "\x00" in dockerfile:
            raise RuntimeError("Dockerfile contains invalid bytes")

        instructions = []
        logical_lines: list[str] = []
        current = ""
        for raw_line in dockerfile.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            current = f"{current} {line}".strip()
            if current.endswith("\\"):
                current = current[:-1].strip()
                continue
            logical_lines.append(current)
            current = ""

        if current:
            logical_lines.append(current)

        for line in logical_lines:
            match = re.match(r"^([a-zA-Z]+)\b", line)
            if match is None:
                raise RuntimeError("Dockerfile contains an invalid instruction")
            instruction = match.group(1).upper()
            instructions.append(instruction)
            if instruction not in SAFE_DOCKERFILE_INSTRUCTIONS:
                raise RuntimeError(f"Dockerfile instruction {instruction} is not allowed")
            if instruction == "ADD" and re.search(r"\shttps?://", line, flags=re.IGNORECASE):
                raise RuntimeError("Dockerfile ADD from remote URLs is not allowed; use COPY or RUN with explicit fetching")
            if instruction == "FROM" and re.search(r"\bscratch\b", line, flags=re.IGNORECASE):
                raise RuntimeError("Dockerfile FROM scratch is not allowed")

        if "FROM" not in instructions:
            raise RuntimeError("Dockerfile must include a FROM instruction")
