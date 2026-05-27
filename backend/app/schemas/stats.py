from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class StatsResponse(BaseModel):
    deployment_id: int
    cpu_usage_percent: float
    ram_usage_bytes: int
    ram_limit_bytes: int
    uptime_seconds: int
    restart_count: int
    running: bool
    collected_at: datetime | None = None


class InstanceStatsResponse(StatsResponse):
    instance_index: int
    container_id: str
    assigned_port: int


class DailyDeploymentStatsResponse(BaseModel):
    day: str
    request_count: int
    avg_ram_usage_bytes: int
    max_ram_usage_bytes: int
