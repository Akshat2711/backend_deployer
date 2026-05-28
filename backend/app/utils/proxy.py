from __future__ import annotations

import logging
from typing import Any
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import StreamingResponse
import httpx
import structlog
from app.core.config import settings

logger = structlog.get_logger()

async def proxy_request(
    request: Request,
    port: int,
    path: str,
    deployment: Any | None = None,
) -> Response:
    # 1. Forward query parameters excluding routing hints
    forward_params = []
    for k, v in request.query_params.multi_items():
        if k not in {"instance_port", "container_port"}:
            forward_params.append(f"{k}={v}")
    target_query = f"?{'&'.join(forward_params)}" if forward_params else ""
    target_path = f"/{path.lstrip('/')}" if path else "/"

    # 2. Get target container ID and IP (if available)
    container_id = None
    container_ip = None
    inspected = None

    if deployment:
        container_ids = [cid for cid in (deployment.container_ids or ([deployment.container_id] if deployment.container_id else [])) if cid]
        assigned_ports = [int(p) for p in (deployment.assigned_ports or ([deployment.assigned_port] if deployment.assigned_port else [])) if p]
        
        for idx, cid, p in zip(range(len(container_ids)), container_ids, assigned_ports):
            if p == port:
                container_id = cid
                break
        
        if container_id is None and container_ids:
            container_id = container_ids[0]

    if container_id:
        try:
            docker_manager = request.app.state.docker_manager
            inspected = await docker_manager.inspect_container(container_id)
            network_name = settings.docker_network
            networks = inspected.get("NetworkSettings", {}).get("Networks", {})
            container_ip = networks.get(network_name, {}).get("IPAddress")
            if not container_ip:
                for net in networks.values():
                    if net.get("IPAddress"):
                        container_ip = net["IPAddress"]
                        break
        except Exception as exc:
            logger.warning("proxy_inspect_container_failed", container_id=container_id, error=str(exc))

    # 3. Build list of potential internal ports to try
    target_ports = []
    
    # 3a. Custom requested container port
    requested_container_port = request.query_params.get("container_port")
    if requested_container_port:
        try:
            target_ports.append(int(requested_container_port))
        except ValueError:
            pass
            
    # 3b. Configured internal port
    if deployment and deployment.internal_port not in target_ports:
        target_ports.append(deployment.internal_port)
        
    # 3c. Exposed ports in container config
    if inspected:
        try:
            exposed = inspected.get("Config", {}).get("ExposedPorts", {}) or {}
            for ep in exposed.keys():
                try:
                    p_val = int(ep.split("/")[0])
                    if p_val not in target_ports:
                        target_ports.append(p_val)
                except Exception:
                    pass
        except Exception:
            pass
            
    # 3d. Common fallbacks
    for cp in [80, 8080, 8000, 3000, 5000]:
        if cp not in target_ports:
            target_ports.append(cp)

    # 4. Copy request headers and add client IP
    headers = {k: v for k, v in request.headers.items()}
    if "x-forwarded-for" not in headers and request.client:
        headers["x-forwarded-for"] = request.client.host

    body = await request.body()
    client: httpx.AsyncClient = request.app.state.http_client

    # 5. Formulate connection order
    connection_attempts = []
    if container_ip:
        for tp in target_ports:
            connection_attempts.append((f"http://{container_ip}:{tp}", f"{container_ip}:{tp}"))
    connection_attempts.append((f"http://localhost:{port}", f"localhost:{port}"))

    res = None
    last_exc = None
    for base_url, host_header in connection_attempts:
        target_url = f"{base_url}{target_path}{target_query}"
        
        headers_to_send = {k: v for k, v in headers.items()}
        headers_to_send["host"] = host_header

        try:
            req = client.build_request(
                method=request.method,
                url=target_url,
                headers=headers_to_send,
                content=body,
            )
            res = await client.send(req, stream=True)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            logger.info("proxy_connection_attempt_failed", url=target_url, error=str(exc))
            continue

    if res is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, 
            detail=f"Proxy error: All connection attempts failed. Last error: {str(last_exc)}"
        )

    exclude_headers = {
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
    res_headers = {
        k: v for k, v in res.headers.items()
        if k.lower() not in exclude_headers
    }

    async def stream_chunks():
        try:
            async for chunk in res.aiter_raw():
                yield chunk
        finally:
            await res.aclose()

    return StreamingResponse(
        stream_chunks(),
        status_code=res.status_code,
        headers=res_headers,
    )
