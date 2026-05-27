from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://paas:paas@localhost:5432/paas"
    jwt_secret: str = Field(default="change-me-in-production", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    frontend_origin: str = "http://localhost:3000"

    docker_network: str = "paas_isolated"
    docker_internal_port: int = 8080
    docker_host_port_start: int = 20000
    docker_host_port_end: int = 30000
    docker_read_only_default: bool = False
    docker_auto_restart_unhealthy: bool = False
    docker_build_network: str = "bridge"
    dockerfile_max_bytes: int = 64_000
    docker_context_max_bytes: int = 10_000_000
    docker_context_max_files: int = 500
    dockerfile_build_timeout_seconds: int = 300
    container_exec_timeout_seconds: int = 20
    container_exec_max_output_bytes: int = 200_000
    container_workspace_root: str = "/app"
    container_file_max_bytes: int = 1_000_000

    resource_pool_max_cpu: float = 4.0
    resource_pool_max_ram_mb: int = 4096
    resource_pool_max_storage_mb: int = 32768
    resource_pool_max_pids: int = 1024
    resource_pool_max_deployments: int = 20
    resource_pool_max_instances_per_deployment: int = 8
    autoscale_cpu_threshold_percent: float = 75.0

    log_level: str = "INFO"
    monitor_interval_seconds: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
