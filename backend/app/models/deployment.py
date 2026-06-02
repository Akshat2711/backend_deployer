from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Deployment(Base):
    __tablename__ = "deployments"

    __table_args__ = (
        UniqueConstraint("user_id", "custom_name", name="uq_user_custom_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    custom_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    image_name: Mapped[str] = mapped_column(String(512))
    container_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, nullable=True)
    container_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="creating")
    cpu_limit: Mapped[float] = mapped_column(Float, default=0.25)
    ram_limit: Mapped[int] = mapped_column(Integer, default=128)
    storage_limit_mb: Mapped[int] = mapped_column(Integer, default=512)
    pids_limit: Mapped[int] = mapped_column(Integer, default=64)
    scale_mode: Mapped[str] = mapped_column(String(16), default="manual")
    desired_instances: Mapped[int] = mapped_column(Integer, default=1)
    assigned_port: Mapped[int] = mapped_column(Integer)
    assigned_ports: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    internal_port: Mapped[int] = mapped_column(Integer, default=8080)
    read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    source_type: Mapped[str] = mapped_column(String(16), default="image")
    github_repo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    github_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    github_context_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    github_auto_deploy: Mapped[bool] = mapped_column(Boolean, default=False)
    github_webhook_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    github_last_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="deployments")
    usage_stats = relationship("UsageStats", back_populates="deployment", cascade="all, delete-orphan")
    daily_stats = relationship("DeploymentDailyStat", back_populates="deployment", cascade="all, delete-orphan")
