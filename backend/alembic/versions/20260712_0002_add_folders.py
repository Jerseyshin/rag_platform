"""add folders

Revision ID: 20260712_0002
Revises: 20260702_0001
Create Date: 2026-07-12
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260712_0002"
down_revision: str | None = "20260702_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_FOLDER_ID = "fld_uncategorized"
DEFAULT_FOLDER_NAME = "未归档"


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "parent_id",
            sa.String(length=36),
            sa.ForeignKey("folders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_folders_parent", "folders", ["parent_id"])

    op.add_column("files", sa.Column("folder_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_files_folder_id_folders",
        "files",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_files_folder_id", "files", ["folder_id"])

    folders = sa.table(
        "folders",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        folders,
        [
            {
                "id": DEFAULT_FOLDER_ID,
                "name": DEFAULT_FOLDER_NAME,
                "sort_order": 0,
            }
        ],
    )
    op.execute(
        f"UPDATE files SET folder_id = '{DEFAULT_FOLDER_ID}' WHERE folder_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("idx_files_folder_id", table_name="files")
    op.drop_constraint("fk_files_folder_id_folders", "files", type_="foreignkey")
    op.drop_column("files", "folder_id")
    op.drop_index("idx_folders_parent", table_name="folders")
    op.drop_table("folders")
