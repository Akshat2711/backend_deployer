"""add storage and scaling fields

Revision ID: 0002_storage_scaling
Revises: 0001_initial
Create Date: 2026-05-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_storage_scaling"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("storage_limit_mb", sa.Integer(), nullable=False, server_default="512"))
    op.add_column("deployments", sa.Column("container_ids", sa.JSON(), nullable=True))
    op.add_column("deployments", sa.Column("storage_limit_mb", sa.Integer(), nullable=False, server_default="512"))
    op.add_column("deployments", sa.Column("scale_mode", sa.String(length=16), nullable=False, server_default="manual"))
    op.add_column("deployments", sa.Column("desired_instances", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("deployments", sa.Column("assigned_ports", sa.JSON(), nullable=True))

    op.execute("UPDATE deployments SET container_ids = json_build_array(container_id) WHERE container_id IS NOT NULL")
    op.execute("UPDATE deployments SET assigned_ports = json_build_array(assigned_port) WHERE assigned_port IS NOT NULL")

    op.alter_column("plans", "storage_limit_mb", server_default=None)
    op.alter_column("deployments", "storage_limit_mb", server_default=None)
    op.alter_column("deployments", "scale_mode", server_default=None)
    op.alter_column("deployments", "desired_instances", server_default=None)


def downgrade() -> None:
    op.drop_column("deployments", "assigned_ports")
    op.drop_column("deployments", "desired_instances")
    op.drop_column("deployments", "scale_mode")
    op.drop_column("deployments", "storage_limit_mb")
    op.drop_column("deployments", "container_ids")
    op.drop_column("plans", "storage_limit_mb")
