from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal
from app.models.deployment import Deployment
from app.services.docker_manager import DockerManagerError

router = APIRouter()


@router.websocket("/ws/logs/{deployment_id}")
async def stream_deployment_logs(websocket: WebSocket, deployment_id: int) -> None:
    token = websocket.query_params.get("token")
    user_id = decode_access_token(token) if token else None
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Deployment).where(Deployment.id == deployment_id, Deployment.user_id == int(user_id))
        )
        deployment = result.scalar_one_or_none()

    if deployment is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
    instance_index_raw = websocket.query_params.get("instance_index") or "1"
    try:
        instance_index = int(instance_index_raw)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if instance_index < 1 or instance_index > len(container_ids):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    container_id = container_ids[instance_index - 1]

    await websocket.accept()
    try:
        async for line in websocket.app.state.docker_manager.stream_logs(container_id):
            await websocket.send_text(line)
    except WebSocketDisconnect:
        return
    except DockerManagerError as exc:
        await websocket.send_json({"error": str(exc)})
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
