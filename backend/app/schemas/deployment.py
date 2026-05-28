from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DeploymentCreate(BaseModel):
    image_name: str = Field(min_length=1, max_length=512, examples=["nginx:alpine"])
    internal_port: int = Field(default=8080, ge=1, le=65535)
    cpu_limit: float = Field(default=0.25, ge=0.05, le=4.0)
    ram_limit: int = Field(default=128, ge=32, le=4096, description="RAM limit in MB")
    storage_limit_mb: int = Field(default=512, ge=16, le=32768, description="Writable container size cap in MB")
    pids_limit: int = Field(default=64, ge=16, le=1024)
    scale_mode: Literal["manual", "auto"] = "manual"
    desired_instances: int = Field(default=1, ge=1, le=8)
    read_only: bool | None = None

    @field_validator("image_name")
    @classmethod
    def validate_image_name(cls, value: str) -> str:
        disallowed = [";", "&", "|", "$", "`", " "]
        if any(token in value for token in disallowed):
            raise ValueError("image name contains invalid characters")
        return value


class GithubDeploymentCreate(DeploymentCreate):
    image_name: str = "github-repo"
    github_repo_url: str = Field(min_length=1, max_length=512)
    github_branch: str = Field(default="main", min_length=1, max_length=128)
    github_context_path: str = Field(default=".", min_length=1, max_length=256)
    github_auto_deploy: bool = False

    @field_validator("github_repo_url")
    @classmethod
    def validate_github_repo_url(cls, value: str) -> str:
        if not value.startswith("https://github.com/"):
            raise ValueError("repo URL must be an https://github.com/... URL")
        if any(token in value for token in [";", "&", "|", "$", "`", " "]):
            raise ValueError("repo URL contains invalid characters")
        return value

    @field_validator("github_branch")
    @classmethod
    def validate_github_branch(cls, value: str) -> str:
        if any(token in value for token in [";", "&", "|", "$", "`", " ", "..", "~", "^", ":"]):
            raise ValueError("branch contains invalid characters")
        return value

    @field_validator("github_context_path")
    @classmethod
    def validate_github_context_path(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if normalized in {"", "."}:
            return "."
        if normalized.startswith(".") or ".." in normalized.split("/"):
            raise ValueError("context path must be a safe relative path")
        if any(token in normalized for token in ["\\", ";", "&", "|", "$", "`", "~", ":"]):
            raise ValueError("context path contains invalid characters")
        return normalized


class DeploymentResponse(BaseModel):
    id: int
    user_id: int
    image_name: str
    container_id: str | None
    container_ids: list[str] | None
    status: str
    cpu_limit: float
    ram_limit: int
    storage_limit_mb: int
    pids_limit: int
    scale_mode: str
    desired_instances: int
    assigned_port: int
    assigned_ports: list[int] | None
    internal_port: int
    read_only: bool
    source_type: str
    github_repo_url: str | None
    github_branch: str | None
    github_context_path: str | None
    github_auto_deploy: bool
    github_webhook_secret: str | None
    github_last_commit: str | None
    restart_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResourcePoolResponse(BaseModel):
    max_cpu: float
    used_cpu: float
    available_cpu: float
    max_ram_mb: int
    used_ram_mb: int
    available_ram_mb: int
    max_storage_mb: int
    used_storage_mb: int
    available_storage_mb: int
    max_pids: int
    used_pids: int
    available_pids: int
    max_deployments: int
    active_deployments: int


class ExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    workdir: str | None = Field(default=None, max_length=512)


class ExecResponse(BaseModel):
    exit_code: int
    output: str


class FileEntry(BaseModel):
    path: str
    kind: str


class FileListResponse(BaseModel):
    path: str
    entries: list[FileEntry]


class FileReadResponse(BaseModel):
    path: str
    content: str


class FileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=1_000_000)


class InstanceLogResponse(BaseModel):
    deployment_id: int
    instance_index: int
    container_id: str
    assigned_port: int | None
    logs: str
