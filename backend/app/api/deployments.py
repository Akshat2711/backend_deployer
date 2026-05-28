from __future__ import annotations

import hashlib
import hmac
import json
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.deployment import Deployment
from app.models.user import User
from app.schemas.deployment import (
    DeploymentCreate,
    DeploymentResponse,
    ExecRequest,
    ExecResponse,
    FileListResponse,
    FileReadResponse,
    FileWriteRequest,
    GithubDeploymentCreate,
    InstanceLogResponse,
    ResourcePoolResponse,
)
from app.schemas.stats import DailyDeploymentStatsResponse, InstanceStatsResponse, StatsResponse
from app.services.deployment_service import GithubRepositoryError
from app.services.docker_manager import DockerManagerError
from app.utils.container_paths import safe_workspace_path
from app.utils.proxy import proxy_request

router = APIRouter(tags=["deployments"])
logger = structlog.get_logger()


def deployment_containers(deployment: Deployment) -> list[tuple[int, str, int | None]]:
    container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
    assigned_ports = [int(port) for port in (deployment.assigned_ports or ([deployment.assigned_port] if deployment.assigned_port else [])) if port]
    return [
        (index + 1, container_id, assigned_ports[index] if index < len(assigned_ports) else None)
        for index, container_id in enumerate(container_ids)
    ]


def select_deployment_container(deployment: Deployment, instance_index: int) -> tuple[int, str, int | None]:
    containers = deployment_containers(deployment)
    if not containers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment has no containers")
    if instance_index < 1 or instance_index > len(containers):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return containers[instance_index - 1]


def deployment_target_url(request: Request, *, port: int, path: str, query: str) -> str:
    target_path = f"/{path.lstrip('/')}" if path else "/"
    target_query = f"?{query}" if query else ""
    if settings.deployment_url_template:
        return (
            settings.deployment_url_template.replace("{port}", str(port))
            .replace("{path}", target_path)
            .replace("{query}", target_query)
            .replace("{scheme}", request.url.scheme)
            .replace("{host}", request.url.hostname or "")
        )

    public_base = settings.public_api_base_url
    parsed_public = urlparse(public_base) if public_base else None
    scheme = parsed_public.scheme if parsed_public and parsed_public.scheme else request.url.scheme
    host = parsed_public.hostname if parsed_public and parsed_public.hostname else request.url.hostname
    if not host:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Public host is not configured")
    return f"{scheme}://{host}:{port}{target_path}{target_query}"


@router.post("/deploy", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
async def deploy(
    payload: DeploymentCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    service = request.app.state.deployment_service
    try:
        return await service.create_deployment(db, user_id=current_user.id, payload=payload)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/deploy/dockerfile", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
async def deploy_dockerfile(
    request: Request,
    dockerfile: UploadFile = File(...),
    context_archive: UploadFile | None = File(default=None),
    internal_port: int = Form(default=8080, ge=1, le=65535),
    cpu_limit: float = Form(default=0.25, ge=0.05, le=4.0),
    ram_limit: int = Form(default=128, ge=32, le=4096),
    storage_limit_mb: int = Form(default=512, ge=16, le=32768),
    pids_limit: int = Form(default=64, ge=16, le=1024),
    scale_mode: Literal["manual", "auto"] = Form(default="manual"),
    desired_instances: int = Form(default=1, ge=1, le=8),
    read_only: bool | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    if dockerfile.filename and dockerfile.filename not in {"Dockerfile", "dockerfile"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a file named Dockerfile")

    raw_dockerfile = await dockerfile.read(settings.dockerfile_max_bytes + 1)
    if len(raw_dockerfile) > settings.dockerfile_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Dockerfile exceeds {settings.dockerfile_max_bytes} byte limit",
        )

    try:
        dockerfile_text = raw_dockerfile.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dockerfile must be UTF-8 text") from exc

    context_bytes: bytes | None = None
    context_filename: str | None = None
    if context_archive is not None:
        context_filename = context_archive.filename or ""
        context_bytes = await context_archive.read(settings.docker_context_max_bytes + 1)
        if len(context_bytes) > settings.docker_context_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Build context exceeds {settings.docker_context_max_bytes} byte limit",
            )

    payload = DeploymentCreate(
        image_name="dockerfile-upload",
        internal_port=internal_port,
        cpu_limit=cpu_limit,
        ram_limit=ram_limit,
        storage_limit_mb=storage_limit_mb,
        pids_limit=pids_limit,
        scale_mode=scale_mode,
        desired_instances=desired_instances,
        read_only=read_only,
    )

    service = request.app.state.deployment_service
    try:
        return await service.create_dockerfile_deployment(
            db,
            user_id=current_user.id,
            payload=payload,
            dockerfile=dockerfile_text,
            context_archive=context_bytes,
            context_filename=context_filename,
        )
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/deploy/github", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
async def deploy_github(
    payload: GithubDeploymentCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    service = request.app.state.deployment_service
    try:
        return await service.create_github_deployment(db, user_id=current_user.id, payload=payload)
    except GithubRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/deployment/{deployment_id}/github/redeploy", response_model=DeploymentResponse)
async def redeploy_github(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    try:
        return await request.app.state.deployment_service.rebuild_github_deployment(db, deployment=deployment)
    except GithubRepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/webhooks/github/{deployment_id}/{webhook_secret}")
async def github_webhook(
    deployment_id: int,
    webhook_secret: str,
    request: Request,
    github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    github_signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    deployment = await request.app.state.deployment_service.get_public_deployment(db, deployment_id=deployment_id)
    if deployment is None or deployment.source_type != "github" or deployment.github_webhook_secret != webhook_secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    if not deployment.github_auto_deploy:
        return {"status": "ignored", "detail": "Auto deploy is disabled for this deployment"}

    body = await request.body()
    if github_signature:
        expected = "sha256=" + hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, github_signature):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    if github_event == "ping":
        return {"status": "ready", "detail": "Webhook connected"}
    if github_event and github_event != "push":
        return {"status": "ignored", "detail": f"Ignored {github_event} event"}

    payload = json.loads(body or b"{}")
    pushed_ref = str(payload.get("ref", ""))
    expected_ref = f"refs/heads/{deployment.github_branch or 'main'}"
    if pushed_ref and pushed_ref != expected_ref:
        return {"status": "ignored", "detail": f"Ignored {pushed_ref}; expected {expected_ref}"}

    after_sha = str(payload.get("after", ""))
    if after_sha and deployment.github_last_commit == after_sha:
        return {"status": "ignored", "detail": "Deployment is already on this commit"}

    try:
        await request.app.state.deployment_service.rebuild_github_deployment(db, deployment=deployment)
    except (GithubRepositoryError, DockerManagerError, RuntimeError) as exc:
        deployment.status = "failed"
        deployment.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "deployed", "detail": deployment.github_last_commit or ""}


@router.get("/resource-pool", response_model=ResourcePoolResponse)
async def resource_pool(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, float | int]:
    _ = current_user
    return await request.app.state.deployment_service.resource_pool(db)


@router.get("/deployments", response_model=list[DeploymentResponse])
async def list_deployments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Deployment]:
    result = await db.execute(select(Deployment).where(Deployment.user_id == current_user.id).order_by(Deployment.created_at.desc()))
    return list(result.scalars().all())


@router.get("/deployment/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    return deployment


@router.api_route(
    "/deployment/{deployment_id}/route",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
@router.api_route(
    "/deployment/{deployment_id}/route/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def route_deployment_traffic(
    deployment_id: int,
    request: Request,
    path: str = "",
    db: AsyncSession = Depends(get_db),
) -> Response:
    deployment = await request.app.state.deployment_service.get_public_deployment(db, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")

    # Check if a specific instance port is requested via query param
    requested_port = request.query_params.get("instance_port")
    port = None
    if requested_port:
        try:
            p_val = int(requested_port)
            assigned_ports = [
                int(p) for p in (deployment.assigned_ports or ([deployment.assigned_port] if deployment.assigned_port else [])) if p
            ]
            if p_val in assigned_ports:
                port = p_val
        except ValueError:
            pass

    if port is None:
        try:
            port = await request.app.state.deployment_service.choose_route_port(deployment)
        except DockerManagerError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    try:
        await request.app.state.deployment_service.record_route_request(db, deployment_id=deployment.id)
    except Exception as exc:
        logger.warning("deployment_route_request_count_failed", deployment_id=deployment.id, error=str(exc))

    response = await proxy_request(
        request,
        port=port,
        path=path,
        deployment=deployment,
    )
    # Set cookies so the 404 fallback proxy can capture absolute subpaths
    response.set_cookie("deploy_id", str(deployment_id), path="/")
    response.set_cookie("deploy_port", str(port), path="/")
    print(f"[DEBUG]Routing request for deployment {deployment_id} to port {port} (path: /{path}, query: {request.url.query})")
    return response



@router.get("/deployment/{deployment_id}/daily-stats", response_model=list[DailyDeploymentStatsResponse])
async def get_daily_stats(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, int | str]]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    return await request.app.state.deployment_service.deployment_daily_stats(db, deployment_id=deployment.id, days=5)


@router.get("/deployment/{deployment_id}/logs")
async def get_logs(
    deployment_id: int,
    request: Request,
    tail: int = Query(default=200, ge=1, le=5000),
    instance_index: int = Query(default=1, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    _, container_id, _ = select_deployment_container(deployment, instance_index)
    try:
        logs = await request.app.state.docker_manager.get_logs(container_id, tail=tail)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"logs": logs}


@router.get("/deployment/{deployment_id}/instances/logs", response_model=list[InstanceLogResponse])
async def get_instance_logs(
    deployment_id: int,
    request: Request,
    tail: int = Query(default=200, ge=1, le=5000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InstanceLogResponse]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")

    rows: list[InstanceLogResponse] = []
    for instance_index, container_id, assigned_port in deployment_containers(deployment):
        try:
            logs = await request.app.state.docker_manager.get_logs(container_id, tail=tail)
        except DockerManagerError as exc:
            logs = str(exc)
        rows.append(
            InstanceLogResponse(
                deployment_id=deployment.id,
                instance_index=instance_index,
                container_id=container_id,
                assigned_port=assigned_port,
                logs=logs,
            )
        )
    return rows


@router.get("/deployment/{deployment_id}/stats", response_model=StatsResponse)
async def get_stats(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None or not deployment.container_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    try:
        stats = await request.app.state.docker_manager.get_stats(deployment.container_id)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return StatsResponse(deployment_id=deployment.id, **{k: stats[k] for k in StatsResponse.model_fields if k in stats})


@router.get("/deployment/{deployment_id}/instances/stats", response_model=list[InstanceStatsResponse])
async def get_instance_stats(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InstanceStatsResponse]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None or not (deployment.container_id or deployment.container_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")

    container_ids = [cid for cid in (deployment.container_ids or [deployment.container_id]) if cid]
    assigned_ports = [int(port) for port in (deployment.assigned_ports or [deployment.assigned_port]) if port]
    rows: list[InstanceStatsResponse] = []
    for index, container_id in enumerate(container_ids):
        try:
            stats = await request.app.state.docker_manager.get_stats(container_id)
        except DockerManagerError:
            continue
        rows.append(
            InstanceStatsResponse(
                deployment_id=deployment.id,
                instance_index=index + 1,
                container_id=container_id,
                assigned_port=assigned_ports[index] if index < len(assigned_ports) else deployment.assigned_port,
                **{key: stats[key] for key in StatsResponse.model_fields if key in stats},
            )
        )

    if not rows:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No instance stats available")
    return rows


@router.post("/deployment/{deployment_id}/exec", response_model=ExecResponse)
async def exec_in_deployment(
    deployment_id: int,
    payload: ExecRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None or not deployment.container_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    try:
        workdir = safe_workspace_path(payload.workdir, workspace_root=settings.container_workspace_root) if payload.workdir else settings.container_workspace_root
        return await request.app.state.docker_manager.exec_command(deployment.container_id, command=payload.command, workdir=workdir)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/deployment/{deployment_id}/files", response_model=FileListResponse)
async def list_container_files(
    deployment_id: int,
    request: Request,
    path: str = Query(default=None),
    instance_index: int = Query(default=1, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    _, container_id, _ = select_deployment_container(deployment, instance_index)
    safe_path = safe_workspace_path(path, workspace_root=settings.container_workspace_root)
    try:
        entries = await request.app.state.docker_manager.list_files(container_id, path=safe_path)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"path": safe_path, "entries": entries}


@router.get("/deployment/{deployment_id}/file", response_model=FileReadResponse)
async def read_container_file(
    deployment_id: int,
    request: Request,
    path: str = Query(..., min_length=1, max_length=512),
    instance_index: int = Query(default=1, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    _, container_id, _ = select_deployment_container(deployment, instance_index)
    safe_path = safe_workspace_path(path, workspace_root=settings.container_workspace_root)
    try:
        content = await request.app.state.docker_manager.read_file(container_id, path=safe_path)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"path": safe_path, "content": content}


@router.put("/deployment/{deployment_id}/file", response_model=FileReadResponse)
async def write_container_file(
    deployment_id: int,
    payload: FileWriteRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    safe_path = safe_workspace_path(payload.path, workspace_root=settings.container_workspace_root)
    containers = deployment_containers(deployment)
    if not containers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment has no containers")
    try:
        for _, container_id, _ in containers:
            await request.app.state.docker_manager.write_file(container_id, path=safe_path, content=payload.content.encode("utf-8"))
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"path": safe_path, "content": payload.content}


@router.post("/deployment/{deployment_id}/file/upload", response_model=FileReadResponse)
async def upload_container_file(
    deployment_id: int,
    request: Request,
    file: UploadFile = File(...),
    path: str = Form(..., min_length=1, max_length=512),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    safe_path = safe_workspace_path(path, workspace_root=settings.container_workspace_root)
    content = await file.read(settings.container_file_max_bytes + 1)
    if len(content) > settings.container_file_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds upload size limit")
    containers = deployment_containers(deployment)
    if not containers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment has no containers")
    try:
        for _, container_id, _ in containers:
            await request.app.state.docker_manager.write_file(container_id, path=safe_path, content=content)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"path": safe_path, "content": content.decode("utf-8", errors="replace")}


@router.post("/restart/{deployment_id}", response_model=DeploymentResponse)
async def restart_deployment(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None or not (deployment.container_id or deployment.container_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    container_ids = [cid for cid in (deployment.container_ids or [deployment.container_id]) if cid]
    try:
        for container_id in container_ids:
            await request.app.state.docker_manager.restart_container(container_id)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    deployment.status = "running"
    deployment.restart_count += 1
    deployment.last_error = None
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.post("/stop/{deployment_id}", response_model=DeploymentResponse)
async def stop_deployment(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Deployment:
    deployment = await request.app.state.deployment_service.get_owned_deployment(db, user_id=current_user.id, deployment_id=deployment_id)
    if deployment is None or not (deployment.container_id or deployment.container_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    container_ids = [cid for cid in (deployment.container_ids or [deployment.container_id]) if cid]
    try:
        for container_id in container_ids:
            await request.app.state.docker_manager.stop_container(container_id)
    except DockerManagerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    deployment.status = "stopped"
    await db.commit()
    await db.refresh(deployment)
    return deployment


@router.delete("/deployment/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deployment(
    deployment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):  
    deployment = await request.app.state.deployment_service.get_owned_deployment(
        db, user_id=current_user.id, deployment_id=deployment_id
    )
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
        
    container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
    for container_id in container_ids:
        await request.app.state.docker_manager.remove_container(container_id, force=True)
    await db.delete(deployment)
    await db.commit()
    return 
