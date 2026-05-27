from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    cpu_limit: Mapped[float] = mapped_column(Float, default=0.25)
    ram_limit_mb: Mapped[int] = mapped_column(Integer, default=128)
    storage_limit_mb: Mapped[int] = mapped_column(Integer, default=512)
    pids_limit: Mapped[int] = mapped_column(Integer, default=64)
    max_deployments: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
