"""add github context path

Revision ID: 0006_add_github_context_path
Revises: 0005_github_deployments
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_add_github_context_path"
down_revision: Union[str, None] = "0005_github_deployments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("deployments")}
    if "github_context_path" not in columns:
        op.add_column("deployments", sa.Column("github_context_path", sa.String(length=256), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("deployments")}
    if "github_context_path" in columns:
        op.drop_column("deployments", "github_context_path")
