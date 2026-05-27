from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UsageStats(Base):
    __tablename__ = "usage_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id", ondelete="CASCADE"), unique=True, index=True)
    cpu_usage_percent: Mapped[float] = mapped_column(Float, default=0.0)
    ram_usage_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    ram_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    uptime_seconds: Mapped[int] = mapped_column(Integer, default=0)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    deployment = relationship("Deployment", back_populates="usage_stats")
