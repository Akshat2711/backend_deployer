"""add deployment daily stats

Revision ID: 0004_deployment_daily_stats
Revises: 0003_latest_usage_stats_only
Create Date: 2026-05-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_deployment_daily_stats"
down_revision: Union[str, None] = "0003_latest_usage_stats_only"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deployment_daily_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ram_usage_total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ram_usage_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ram_usage_max_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deployment_id", "day", name="uq_deployment_daily_stats_deployment_day"),
    )
    op.create_index(op.f("ix_deployment_daily_stats_deployment_id"), "deployment_daily_stats", ["deployment_id"], unique=False)
    op.create_index(op.f("ix_deployment_daily_stats_day"), "deployment_daily_stats", ["day"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_deployment_daily_stats_day"), table_name="deployment_daily_stats")
    op.drop_index(op.f("ix_deployment_daily_stats_deployment_id"), table_name="deployment_daily_stats")
    op.drop_table("deployment_daily_stats")
