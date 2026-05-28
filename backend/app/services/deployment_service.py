from __future__ import annotations

import asyncio
import time
import re
import secrets
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.deployment import Deployment
from app.models.deployment_daily_stat import DeploymentDailyStat
from app.models.usage_stats import UsageStats
from app.schemas.deployment import DeploymentCreate, GithubDeploymentCreate
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


class GithubRepositoryError(RuntimeError):
    pass


class DeploymentService:
    def __init__(self, docker_manager: DockerManager) -> None:
        self.docker = docker_manager
        self._capacity_lock = asyncio.Lock()
        self._stats_cache: dict[str, tuple[float, dict]] = {}

    async def create_github_deployment(self, db: AsyncSession, *, user_id: int, payload: GithubDeploymentCreate) -> Deployment:
        self.validate_github_repo_url(payload.github_repo_url)
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
                source_type="github",
                github_repo_url=payload.github_repo_url,
                github_branch=payload.github_branch,
                github_context_path=payload.github_context_path,
                github_auto_deploy=payload.github_auto_deploy,
                github_webhook_secret=secrets.token_urlsafe(24),
            )
            db.add(deployment)
            await db.commit()
            await db.refresh(deployment)

        image_tag = f"server-rent-alpha/user-{user_id}-deployment-{deployment.id}:latest"
        deployment.image_name = image_tag
        await db.commit()

        try:
            await self.rebuild_github_deployment(db, deployment=deployment, image_tag=image_tag)
        except (DockerManagerError, RuntimeError) as exc:
            deployment.status = "failed"
            deployment.last_error = str(exc)
            await db.commit()
            raise

        await db.refresh(deployment)
        return deployment

    async def rebuild_github_deployment(self, db: AsyncSession, *, deployment: Deployment, image_tag: str | None = None) -> Deployment:
        if deployment.source_type != "github" or not deployment.github_repo_url:
            raise RuntimeError("Deployment is not linked to a GitHub repository")

        image_name = image_tag or deployment.image_name
        deployment.status = "building"
        deployment.last_error = None
        await db.commit()

        repo_dir, commit_sha = await self.clone_github_repo(
            repo_url=deployment.github_repo_url,
            branch=deployment.github_branch or "main",
        )
        try:
            context_path = self.resolve_github_context_path(repo_dir=Path(repo_dir), context_path=deployment.github_context_path or ".")
            if not Path(context_path, "Dockerfile").is_file():
                display_path = deployment.github_context_path or "."
                raise RuntimeError(f"GitHub repository must contain a Dockerfile at context path {display_path}")
            await self.docker.build_image_from_path(path=context_path, tag=image_name)
        finally:
            shutil.rmtree(repo_dir, ignore_errors=True)

        old_container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
        for container_id in old_container_ids:
            await self.docker.remove_container(container_id, force=True)

        deployment.container_id = None
        deployment.container_ids = []
        deployment.assigned_ports = []
        deployment.status = "creating"
        await db.commit()

        await self.create_runtime_containers(db, deployment=deployment)
        deployment.github_last_commit = commit_sha
        deployment.status = "running"
        deployment.last_error = None
        await db.commit()
        await db.refresh(deployment)
        return deployment

    async def create_runtime_containers(self, db: AsyncSession, *, deployment: Deployment) -> None:
        instance_count = 1 if deployment.scale_mode == "auto" else deployment.desired_instances
        container_ids: list[str] = []
        assigned_ports: list[int] = []

        try:
            for instance_index in range(instance_count):
                host_port = random_available_port(settings.docker_host_port_start, settings.docker_host_port_end)
                assigned_ports.append(host_port)
                container_id = await self.docker.create_container(
                    image_name=deployment.image_name,
                    host_port=host_port,
                    internal_port=deployment.internal_port,
                    cpu_limit=deployment.cpu_limit,
                    ram_limit_mb=deployment.ram_limit,
                    storage_limit_mb=deployment.storage_limit_mb,
                    pids_limit=deployment.pids_limit,
                    read_only=deployment.read_only,
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
            await self.ensure_started_instances_running(container_ids)
        except (DockerManagerError, RuntimeError):
            for container_id in container_ids:
                await self.docker.remove_container(container_id, force=True)
            raise

    async def clone_github_repo(self, *, repo_url: str, branch: str) -> tuple[str, str]:
        target = tempfile.mkdtemp(prefix="server-rent-github-")
        try:
            clone = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                repo_url,
                target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await clone.communicate()
            if clone.returncode != 0:
                raise GithubRepositoryError(stderr.decode("utf-8", errors="replace").strip() or "Git clone failed")

            rev_parse = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                target,
                "rev-parse",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await rev_parse.communicate()
            if rev_parse.returncode != 0:
                raise GithubRepositoryError(stderr.decode("utf-8", errors="replace").strip() or "Could not read commit SHA")
            return target, stdout.decode("utf-8", errors="replace").strip()
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

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
                source_type="image",
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
            await self.ensure_started_instances_running(container_ids)

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
                source_type="dockerfile",
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
            await self.ensure_started_instances_running(container_ids)

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
    
#descides which port to route to based on container stats, returns first assigned port if no running instances are found
    async def choose_route_port(self, deployment: Deployment) -> int:
        container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
        assigned_ports = [int(port) for port in (deployment.assigned_ports or ([deployment.assigned_port] if deployment.assigned_port else []))]

        if deployment.status not in {"running", "degraded"} or not container_ids or not assigned_ports:
            raise RuntimeError("Deployment has no running instances available")

        pairs = list(zip(container_ids, assigned_ports))
        scored_ports: list[tuple[float, int]] = []
        now = time.time()

        # Helper to fetch stats in the background to avoid blocking user requests
        async def fetch_and_cache_stats(c_id: str) -> None:
            try:
                stats = await self.docker.get_stats(c_id)
                self._stats_cache[c_id] = (time.time(), stats)
            except Exception:
                pass

        for container_id, port in pairs:
            cached_data = self._stats_cache.get(container_id)
            if cached_data is None:
                # Cache miss: trigger background fetch and use a default baseline score (0.0)
                asyncio.create_task(fetch_and_cache_stats(container_id))
                score = 0.0
            else:
                cache_time, stats = cached_data
                # Cache hits older than 10 seconds: trigger background refresh, use cached values immediately
                if now - cache_time > 10.0:
                    asyncio.create_task(fetch_and_cache_stats(container_id))
                
                if not stats.get("running", True):
                    continue
                ram_limit = int(stats.get("ram_limit_bytes", 1)) or 1
                ram_percent = (int(stats.get("ram_usage_bytes", 0)) / ram_limit) * 100
                score = float(stats.get("cpu_usage_percent", 0.0)) + ram_percent

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

    async def record_route_request(self, db: AsyncSession, *, deployment_id: int) -> None:
        stmt = insert(DeploymentDailyStat).values(
            deployment_id=deployment_id,
            day=self._today(),
            request_count=1,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_deployment_daily_stats_deployment_day",
            set_={
                "request_count": DeploymentDailyStat.request_count + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await db.execute(stmt)
        await db.commit()

    async def deployment_daily_stats(self, db: AsyncSession, *, deployment_id: int, days: int = 5) -> list[dict[str, int | str]]:
        today = self._today()
        start_day = today - timedelta(days=days - 1)
        result = await db.execute(
            select(DeploymentDailyStat)
            .where(DeploymentDailyStat.deployment_id == deployment_id, DeploymentDailyStat.day >= start_day)
            .order_by(DeploymentDailyStat.day.asc())
        )
        rows_by_day = {row.day: row for row in result.scalars().all()}
        output: list[dict[str, int | str]] = []
        for offset in range(days):
            day = start_day + timedelta(days=offset)
            row = rows_by_day.get(day)
            if row is None:
                output.append(
                    {
                        "day": day.isoformat(),
                        "request_count": 0,
                        "avg_ram_usage_bytes": 0,
                        "max_ram_usage_bytes": 0,
                    }
                )
                continue

            avg_ram_usage_bytes = row.ram_usage_total_bytes // row.ram_usage_samples if row.ram_usage_samples else 0
            output.append(
                {
                    "day": row.day.isoformat(),
                    "request_count": row.request_count,
                    "avg_ram_usage_bytes": avg_ram_usage_bytes,
                    "max_ram_usage_bytes": row.ram_usage_max_bytes,
                }
            )
        return output

    async def _record_daily_memory_sample(self, db: AsyncSession, *, deployment_id: int, ram_usage_bytes: int) -> None:
        stmt = insert(DeploymentDailyStat).values(
            deployment_id=deployment_id,
            day=self._today(),
            ram_usage_total_bytes=ram_usage_bytes,
            ram_usage_samples=1,
            ram_usage_max_bytes=ram_usage_bytes,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_deployment_daily_stats_deployment_day",
            set_={
                "ram_usage_total_bytes": DeploymentDailyStat.ram_usage_total_bytes + ram_usage_bytes,
                "ram_usage_samples": DeploymentDailyStat.ram_usage_samples + 1,
                "ram_usage_max_bytes": func.greatest(DeploymentDailyStat.ram_usage_max_bytes, ram_usage_bytes),
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await db.execute(stmt)

    def _today(self) -> date:
        return datetime.now(timezone.utc).date()

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

    async def ensure_started_instances_running(self, container_ids: list[str]) -> None:
        await asyncio.sleep(settings.docker_container_start_grace_seconds)
        failed: list[str] = []
        for container_id in container_ids:
            inspected = await self.docker.inspect_container(container_id)
            state = inspected.get("State", {})
            if state.get("Running"):
                continue
            logs = await self.docker.get_logs(container_id, tail=60)
            failed.append(f"{container_id[:12]} exited with status {state.get('Status', 'unknown')}: {logs.strip()}")

        if failed:
            raise DockerManagerError("One or more deployment instances failed to start. " + " | ".join(failed))

    async def refresh_instance_health(self, db: AsyncSession, deployment: Deployment) -> None:
        container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
        if not container_ids:
            return

        running_count = 0
        failed_messages: list[str] = []
        for container_id in container_ids:
            try:
                inspected = await self.docker.inspect_container(container_id)
            except DockerManagerError as exc:
                failed_messages.append(str(exc))
                continue

            state = inspected.get("State", {})
            if state.get("Running"):
                running_count += 1
                continue

            failed_messages.append(f"{container_id[:12]} is {state.get('Status', 'unknown')}")

        if running_count == len(container_ids):
            deployment.status = "running"
            deployment.last_error = None
        elif running_count > 0:
            deployment.status = "degraded"
            deployment.last_error = "; ".join(failed_messages)
        else:
            deployment.status = "crashed"
            deployment.last_error = "; ".join(failed_messages)

        await db.commit()

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
        await self._record_daily_memory_sample(db, deployment_id=deployment.id, ram_usage_bytes=stats["ram_usage_bytes"])
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

    def validate_github_repo_url(self, repo_url: str) -> None:
        parsed = urlparse(repo_url)
        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
            raise RuntimeError("Only https://github.com/... repository URLs are supported")
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) < 2:
            raise RuntimeError("GitHub repository URL must include owner and repo")
        if any(part in {".", ".."} for part in parts[:2]):
            raise RuntimeError("GitHub repository URL is invalid")

    def resolve_github_context_path(self, *, repo_dir: Path, context_path: str) -> Path:
        normalized = context_path.strip().strip("/")
        if normalized in {"", "."}:
            return repo_dir.resolve()
        parts = normalized.split("/")
        if normalized.startswith(".") or ".." in parts:
            raise RuntimeError("GitHub context path must be a safe relative path")
        target = (repo_dir / normalized).resolve()
        root = repo_dir.resolve()
        if target != root and root not in target.parents:
            raise RuntimeError("GitHub context path escapes the repository")
        if not target.is_dir():
            raise RuntimeError(f"GitHub context path does not exist: {normalized}")
        return target
