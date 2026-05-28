"""add github deployment metadata

Revision ID: 0005_github_deployments
Revises: 0004_deployment_daily_stats
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_github_deployments"
down_revision: Union[str, None] = "0004_deployment_daily_stats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("deployments", sa.Column("source_type", sa.String(length=16), nullable=False, server_default="image"))
    op.add_column("deployments", sa.Column("github_repo_url", sa.String(length=512), nullable=True))
    op.add_column("deployments", sa.Column("github_branch", sa.String(length=128), nullable=True))
    op.add_column("deployments", sa.Column("github_context_path", sa.String(length=256), nullable=True))
    op.add_column("deployments", sa.Column("github_auto_deploy", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("deployments", sa.Column("github_webhook_secret", sa.String(length=128), nullable=True))
    op.add_column("deployments", sa.Column("github_last_commit", sa.String(length=64), nullable=True))
    op.alter_column("deployments", "source_type", server_default=None)
    op.alter_column("deployments", "github_auto_deploy", server_default=None)


def downgrade() -> None:
    op.drop_column("deployments", "github_last_commit")
    op.drop_column("deployments", "github_webhook_secret")
    op.drop_column("deployments", "github_auto_deploy")
    op.drop_column("deployments", "github_context_path")
    op.drop_column("deployments", "github_branch")
    op.drop_column("deployments", "github_repo_url")
    op.drop_column("deployments", "source_type")
