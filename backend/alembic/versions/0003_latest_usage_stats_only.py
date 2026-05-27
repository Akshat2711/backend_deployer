"""keep one latest usage stats row per deployment

Revision ID: 0003_latest_usage_stats_only
Revises: 0002_storage_scaling
Create Date: 2026-05-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_latest_usage_stats_only"
down_revision: Union[str, None] = "0002_storage_scaling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM usage_stats old
        USING usage_stats newer
        WHERE old.deployment_id = newer.deployment_id
          AND (newer.created_at, newer.id) > (old.created_at, old.id)
        """
    )
    op.drop_index(op.f("ix_usage_stats_deployment_id"), table_name="usage_stats")
    op.create_index(op.f("ix_usage_stats_deployment_id"), "usage_stats", ["deployment_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_stats_deployment_id"), table_name="usage_stats")
    op.create_index(op.f("ix_usage_stats_deployment_id"), "usage_stats", ["deployment_id"], unique=False)
