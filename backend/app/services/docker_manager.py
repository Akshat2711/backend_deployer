from __future__ import annotations

import asyncio
import io
import shutil
import shlex
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.models.containers import Container

from app.core.config import settings


class DockerManagerError(RuntimeError):
    pass


class DockerManager:
    def __init__(self) -> None:
        self.client = docker.from_env()
        self.api = self.client.api

    async def ensure_network(self) -> None:
        await asyncio.to_thread(self._ensure_network_sync)

    def _ensure_network_sync(self) -> None:
        try:
            self.client.networks.get(settings.docker_network)
        except NotFound:
            self.client.networks.create(
                settings.docker_network,
                driver="bridge",
                internal=False,
                attachable=True,
                labels={"managed-by": "server-rent-alpha"},
            )

    async def pull_image(self, image_name: str) -> None:
        try:
            await asyncio.to_thread(self.client.images.pull, image_name)
        except (ImageNotFound, APIError, DockerException) as exc:
            raise DockerManagerError(f"Failed to pull image {image_name}: {exc}") from exc

    async def build_image_from_path(self, *, path: Path, tag: str) -> None:
        await self.ensure_network()
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.images.build,
                    path=str(path),
                    dockerfile="Dockerfile",
                    tag=tag,
                    rm=True,
                    forcerm=True,
                    pull=True,
                    network_mode=settings.docker_build_network,
                    labels={"managed-by": "server-rent-alpha"},
                ),
                timeout=settings.dockerfile_build_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DockerManagerError("GitHub repository build timed out") from exc
        except (APIError, DockerException, OSError) as exc:
            raise DockerManagerError(f"Failed to build GitHub repository image: {exc}") from exc

    async def build_image_from_dockerfile(
        self,
        *,
        dockerfile: str,
        tag: str,
        context_archive: bytes | None = None,
        context_filename: str | None = None,
    ) -> None:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._build_image_from_dockerfile_sync,
                    dockerfile,
                    tag,
                    context_archive,
                    context_filename,
                ),
                timeout=settings.dockerfile_build_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DockerManagerError("Dockerfile build timed out") from exc
        except (APIError, DockerException, OSError) as exc:
            raise DockerManagerError(f"Failed to build Dockerfile image: {exc}") from exc

    def _build_image_from_dockerfile_sync(
        self,
        dockerfile: str,
        tag: str,
        context_archive: bytes | None,
        context_filename: str | None,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="server-rent-build-") as build_dir:
            if context_archive is not None:
                self._extract_context_archive(
                    archive=context_archive,
                    filename=context_filename or "",
                    build_dir=Path(build_dir),
                )
            Path(build_dir, "Dockerfile").write_text(dockerfile, encoding="utf-8")
            self.client.images.build(
                path=build_dir,
                tag=tag,
                rm=True,
                forcerm=True,
                pull=True,
                network_mode=settings.docker_build_network,
                labels={"managed-by": "server-rent-alpha"},
            )

    def _extract_context_archive(self, *, archive: bytes, filename: str, build_dir: Path) -> None:
        lower_name = filename.lower()
        if lower_name.endswith(".zip"):
            self._extract_zip_context(archive=archive, build_dir=build_dir)
            return
        if lower_name.endswith((".tar", ".tar.gz", ".tgz")):
            self._extract_tar_context(archive=archive, build_dir=build_dir)
            return
        raise DockerManagerError("Build context must be a .zip, .tar, .tar.gz, or .tgz archive")

    def _safe_context_path(self, build_dir: Path, member_name: str) -> Path:
        target = (build_dir / member_name).resolve()
        root = build_dir.resolve()
        if target == root or root not in target.parents:
            raise DockerManagerError("Build context contains an unsafe path")
        return target

    def _extract_zip_context(self, *, archive: bytes, build_dir: Path) -> None:
        total_size = 0
        with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
            infos = zip_file.infolist()
            if len(infos) > settings.docker_context_max_files:
                raise DockerManagerError("Build context contains too many files")

            for info in infos:
                total_size += info.file_size
                if total_size > settings.docker_context_max_bytes:
                    raise DockerManagerError("Build context expanded size exceeds limit")
                if info.is_dir():
                    self._safe_context_path(build_dir, info.filename).mkdir(parents=True, exist_ok=True)
                    continue

                file_type = (info.external_attr >> 16) & 0o170000
                if file_type == 0o120000:
                    raise DockerManagerError("Build context symlinks are not allowed")

                target = self._safe_context_path(build_dir, info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _extract_tar_context(self, *, archive: bytes, build_dir: Path) -> None:
        total_size = 0
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tar_file:
            members = tar_file.getmembers()
            if len(members) > settings.docker_context_max_files:
                raise DockerManagerError("Build context contains too many files")

            for member in members:
                if member.isdir():
                    self._safe_context_path(build_dir, member.name).mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise DockerManagerError("Build context may only contain regular files and directories")

                total_size += member.size
                if total_size > settings.docker_context_max_bytes:
                    raise DockerManagerError("Build context expanded size exceeds limit")

                extracted = tar_file.extractfile(member)
                if extracted is None:
                    raise DockerManagerError("Build context contains an unreadable file")

                target = self._safe_context_path(build_dir, member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with extracted, target.open("wb") as dst:
                    shutil.copyfileobj(extracted, dst)

    async def create_container(
        self,
        *,
        image_name: str,
        host_port: int,
        internal_port: int,
        cpu_limit: float,
        ram_limit_mb: int,
        storage_limit_mb: int,
        pids_limit: int,
        read_only: bool,
        name: str,
    ) -> str:
        await self.ensure_network()
        create_kwargs = {
            "image": image_name,
            "name": name,
            "detach": True,
            "network": settings.docker_network,
            "ports": {f"{internal_port}/tcp": host_port},
            "mem_limit": f"{ram_limit_mb}m",
            "nano_cpus": int(cpu_limit * 1_000_000_000),
            "pids_limit": pids_limit,
            "privileged": False,
            "cap_drop": ["ALL"],
            "cap_add": self._cap_adds(image_name),
            "security_opt": ["no-new-privileges:true"],
            "read_only": read_only,
            "tmpfs": self._tmpfs_mounts(image_name, read_only),
            "labels": {"managed-by": "server-rent-alpha"},
        }
        if storage_limit_mb > 0:
            create_kwargs["storage_opt"] = {"size": f"{storage_limit_mb}m"}

        try:
            container = await asyncio.to_thread(self.client.containers.create, **create_kwargs)
            return container.id
        except (APIError, DockerException) as exc:
            if "storage_opt" in create_kwargs and self._is_unsupported_storage_opt_error(exc):
                create_kwargs.pop("storage_opt", None)
                try:
                    container = await asyncio.to_thread(self.client.containers.create, **create_kwargs)
                    return container.id
                except (APIError, DockerException) as retry_exc:
                    raise DockerManagerError(f"Failed to create container: {retry_exc}") from retry_exc
            raise DockerManagerError(f"Failed to create container: {exc}") from exc

    def _is_unsupported_storage_opt_error(self, exc: BaseException) -> bool:
        message = str(exc).lower()
        return "storage-opt" in message and ("supported only" in message or "not supported" in message)

    async def build_image_from_dockerfile(
        self,
        *,
        dockerfile: str,
        tag: str,
        context_archive: bytes | None = None,
        context_filename: str | None = None,
    ) -> None:
        await self.ensure_network()
        try:
            await asyncio.to_thread(
                self._build_image_from_dockerfile_sync,
                dockerfile,
                tag,
                context_archive,
                context_filename,
            )
        except (APIError, DockerException) as exc:
            raise DockerManagerError(f"Failed to build image: {exc}") from exc

    def _build_image_from_dockerfile_sync(
        self,
        dockerfile: str,
        tag: str,
        context_archive: bytes | None,
        context_filename: str | None,
    ) -> None:
        import io
        import tarfile
        import time

        if context_archive is not None:
            tar_stream = io.BytesIO(context_archive)
            tar_stream.seek(0)
            self.client.images.build(
                fileobj=tar_stream,
                custom_context=True,
                dockerfile="Dockerfile",
                tag=tag,
                rm=True,
            )
            return

        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as archive:
            dockerfile_bytes = dockerfile.encode("utf-8")
            tarinfo = tarfile.TarInfo(name=context_filename or "Dockerfile")
            tarinfo.size = len(dockerfile_bytes)
            tarinfo.mtime = int(time.time())
            archive.addfile(tarinfo, io.BytesIO(dockerfile_bytes))
        tar_stream.seek(0)
        self.client.images.build(
            fileobj=tar_stream,
            custom_context=True,
            dockerfile=context_filename or "Dockerfile",
            tag=tag,
            rm=True,
        )

    def _tmpfs_mounts(self, image_name: str, read_only: bool) -> dict[str, str] | None:
        if not read_only:
            return None

        tmpfs = {"/tmp": "rw,noexec,nosuid,size=64m"}
        image_repo = image_name.split("@", 1)[0].split(":", 1)[0].lower()

        if image_repo == "nginx" or image_repo.endswith("/nginx"):
            tmpfs["/var/cache/nginx"] = "rw,noexec,nosuid,size=64m"
            tmpfs["/run"] = "rw,noexec,nosuid,size=16m"
            tmpfs["/var/run"] = "rw,noexec,nosuid,size=16m"

        return tmpfs

    def _cap_adds(self, image_name: str) -> list[str] | None:
        image_repo = image_name.split("@", 1)[0].split(":", 1)[0].lower()
        if image_repo == "nginx" or image_repo.endswith("/nginx"):
            return ["CHOWN", "SETGID", "SETUID"]
        return None

    async def start_container(self, container_id: str) -> None:
        container = await self._get_container(container_id)
        await asyncio.to_thread(container.start)

    async def stop_container(self, container_id: str) -> None:
        container = await self._get_container(container_id)
        await asyncio.to_thread(container.stop, timeout=10)

    async def restart_container(self, container_id: str) -> None:
        container = await self._get_container(container_id)
        await asyncio.to_thread(container.restart, timeout=10)

    async def remove_container(self, container_id: str, *, force: bool = True) -> None:
        try:
            container = await self._get_container(container_id)
            await asyncio.to_thread(container.remove, force=force)
        except DockerManagerError:
            return

    async def get_logs(self, container_id: str, *, tail: int = 200) -> str:
        container = await self._get_container(container_id)
        raw = await asyncio.to_thread(container.logs, stdout=True, stderr=True, tail=tail)
        return raw.decode("utf-8", errors="replace")

    async def exec_command(self, container_id: str, *, command: str, workdir: str | None = None) -> dict[str, str | int]:
        container = await self._get_container(container_id)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    container.exec_run,
                    ["sh", "-lc", command],
                    stdout=True,
                    stderr=True,
                    workdir=workdir,
                ),
                timeout=settings.container_exec_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DockerManagerError("Command timed out") from exc
        except (APIError, DockerException) as exc:
            raise DockerManagerError(f"Failed to execute command: {exc}") from exc

        output = result.output[: settings.container_exec_max_output_bytes].decode("utf-8", errors="replace")
        return {"exit_code": int(result.exit_code), "output": output}

    async def list_files(self, container_id: str, *, path: str) -> list[dict[str, str]]:
        quoted_path = shlex.quote(path)
        command = (
            f"for p in {quoted_path}/* {quoted_path}/.[!.]* {quoted_path}/..?*; do "
            "[ -e \"$p\" ] || continue; "
            "if [ -d \"$p\" ]; then printf 'd %s\\n' \"$p\"; else printf 'f %s\\n' \"$p\"; fi; "
            "done | sort"
        )
        result = await self.exec_command(
            container_id,
            command=command,
        )
        if int(result["exit_code"]) != 0:
            raise DockerManagerError(str(result["output"]))

        entries: list[dict[str, str]] = []
        for line in str(result["output"]).splitlines():
            kind_raw, _, item_path = line.partition(" ")
            kind = "directory" if kind_raw == "d" else "file"
            entries.append({"path": item_path, "kind": kind})
        return entries

    async def read_file(self, container_id: str, *, path: str) -> str:
        container = await self._get_container(container_id)
        try:
            stream, _ = await asyncio.to_thread(container.get_archive, path)
            archive = b"".join(stream)
        except (APIError, DockerException) as exc:
            raise DockerManagerError(f"Failed to read file: {exc}") from exc

        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tar_file:
            members = [member for member in tar_file.getmembers() if member.isfile()]
            if len(members) != 1:
                raise DockerManagerError("Path is not a single readable file")
            member = members[0]
            if member.size > settings.container_file_max_bytes:
                raise DockerManagerError("File exceeds read size limit")
            extracted = tar_file.extractfile(member)
            if extracted is None:
                raise DockerManagerError("File could not be read")
            return extracted.read().decode("utf-8", errors="replace")

    async def write_file(self, container_id: str, *, path: str, content: bytes) -> None:
        if len(content) > settings.container_file_max_bytes:
            raise DockerManagerError("File exceeds write size limit")

        container = await self._get_container(container_id)
        directory = str(Path(path).parent)
        filename = Path(path).name
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar_file:
            info = tarfile.TarInfo(filename)
            info.size = len(content)
            info.mode = 0o644
            tar_file.addfile(info, io.BytesIO(content))
        tar_buffer.seek(0)

        try:
            ok = await asyncio.to_thread(container.put_archive, directory, tar_buffer.read())
        except (APIError, DockerException) as exc:
            raise DockerManagerError(f"Failed to write file: {exc}") from exc
        if not ok:
            raise DockerManagerError("Docker rejected the file upload")

    async def stream_logs(self, container_id: str, *, tail: int = 50) -> AsyncIterator[str]:
        container = await self._get_container(container_id)
        stream = await asyncio.to_thread(container.logs, stream=True, follow=True, stdout=True, stderr=True, tail=tail)
        try:
            while True:
                chunk = await asyncio.to_thread(next, stream, None)
                if chunk is None:
                    break
                yield chunk.decode("utf-8", errors="replace")
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

    async def get_stats(self, container_id: str) -> dict[str, Any]:
        container = await self._get_container(container_id)
        stats = await asyncio.to_thread(container.stats, stream=False)
        inspected = await self.inspect_container(container_id)
        return self._normalize_stats(stats, inspected)

    async def inspect_container(self, container_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self.api.inspect_container, container_id)
        except (NotFound, APIError, DockerException) as exc:
            raise DockerManagerError(f"Container not found: {container_id}") from exc

    async def _get_container(self, container_id: str) -> Container:
        try:
            return await asyncio.to_thread(self.client.containers.get, container_id)
        except (NotFound, APIError, DockerException) as exc:
            raise DockerManagerError(f"Container not found: {container_id}") from exc

    def _normalize_stats(self, stats: dict[str, Any], inspected: dict[str, Any]) -> dict[str, Any]:
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        cpu_usage = cpu_stats.get("cpu_usage", {})
        precpu_usage = precpu_stats.get("cpu_usage", {})
        cpu_delta = cpu_usage.get("total_usage", 0) - precpu_usage.get("total_usage", 0)
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
        online_cpus = cpu_stats.get("online_cpus") or len(cpu_usage.get("percpu_usage", [])) or 1
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0 if system_delta > 0 and cpu_delta > 0 else 0.0

        memory = stats.get("memory_stats", {})
        state = inspected.get("State", {})
        started_at_raw = state.get("StartedAt")
        uptime_seconds = 0
        if started_at_raw and started_at_raw != "0001-01-01T00:00:00Z":
            started_at = datetime.fromisoformat(started_at_raw.replace("Z", "+00:00"))
            uptime_seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))

        return {
            "cpu_usage_percent": round(cpu_percent, 2),
            "ram_usage_bytes": int(memory.get("usage", 0)),
            "ram_limit_bytes": int(memory.get("limit", 0)),
            "uptime_seconds": uptime_seconds,
            "restart_count": int(inspected.get("RestartCount", state.get("RestartCount", 0))),
            "running": bool(state.get("Running", False)),
            "status": str(state.get("Status", "unknown")),
        }
