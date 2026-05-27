from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DeploymentDailyStat(Base):
    __tablename__ = "deployment_daily_stats"
    __table_args__ = (UniqueConstraint("deployment_id", "day", name="uq_deployment_daily_stats_deployment_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    ram_usage_total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    ram_usage_samples: Mapped[int] = mapped_column(Integer, default=0)
    ram_usage_max_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    deployment = relationship("Deployment", back_populates="daily_stats")
