"""add durable file progress

Revision ID: 20260713_0003
Revises: 20260712_0002
Create Date: 2026-07-13
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260713_0003"
down_revision: str | None = "20260712_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("files", sa.Column("progress_percent", sa.Integer(), nullable=True))
    op.add_column("files", sa.Column("progress_stage", sa.String(length=50), nullable=True))
    op.add_column("files", sa.Column("progress_message", sa.Text(), nullable=True))
    op.add_column(
        "files", sa.Column("progress_processed_chunks", sa.Integer(), nullable=True)
    )
    op.add_column("files", sa.Column("progress_total_chunks", sa.Integer(), nullable=True))
    op.add_column(
        "files",
        sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("files", "progress_updated_at")
    op.drop_column("files", "progress_total_chunks")
    op.drop_column("files", "progress_processed_chunks")
    op.drop_column("files", "progress_message")
    op.drop_column("files", "progress_stage")
    op.drop_column("files", "progress_percent")
