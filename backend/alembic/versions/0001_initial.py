"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("cpu_limit", sa.Float(), nullable=False),
        sa.Column("ram_limit_mb", sa.Integer(), nullable=False),
        sa.Column("pids_limit", sa.Integer(), nullable=False),
        sa.Column("max_deployments", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plans_name"), "plans", ["name"], unique=True)

    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("image_name", sa.String(length=512), nullable=False),
        sa.Column("container_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cpu_limit", sa.Float(), nullable=False),
        sa.Column("ram_limit", sa.Integer(), nullable=False),
        sa.Column("pids_limit", sa.Integer(), nullable=False),
        sa.Column("assigned_port", sa.Integer(), nullable=False),
        sa.Column("internal_port", sa.Integer(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("restart_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_deployments_container_id"), "deployments", ["container_id"], unique=True)
    op.create_index(op.f("ix_deployments_id"), "deployments", ["id"], unique=False)
    op.create_index(op.f("ix_deployments_user_id"), "deployments", ["user_id"], unique=False)

    op.create_table(
        "usage_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("cpu_usage_percent", sa.Float(), nullable=False),
        sa.Column("ram_usage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("ram_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uptime_seconds", sa.Integer(), nullable=False),
        sa.Column("restart_count", sa.Integer(), nullable=False),
        sa.Column("running", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_usage_stats_deployment_id"), "usage_stats", ["deployment_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_stats_deployment_id"), table_name="usage_stats")
    op.drop_table("usage_stats")
    op.drop_index(op.f("ix_deployments_user_id"), table_name="deployments")
    op.drop_index(op.f("ix_deployments_id"), table_name="deployments")
    op.drop_index(op.f("ix_deployments_container_id"), table_name="deployments")
    op.drop_table("deployments")
    op.drop_index(op.f("ix_plans_name"), table_name="plans")
    op.drop_table("plans")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
