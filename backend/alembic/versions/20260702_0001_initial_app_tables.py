"""initial app tables

Revision ID: 20260702_0001
Revises: None
Create Date: 2026-07-02
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260702_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_CONFIGS = [
    ("rag.chunk_size", "1024", "新文件默认分片大小，单位 tokens"),
    ("rag.chunk_overlap", "200", "新文件默认分片重叠，单位 tokens"),
    ("rag.default_top_k", "5", "检索默认返回片段数"),
    ("rag.default_threshold", "0.7", "检索默认相关性阈值"),
    ("rag.search_mode", "global", "LightRAG 检索模式，由管理员配置"),
    ("rag.llm_model", "Qwen2.5-72B-Internal", "LightRAG 索引和查询使用的 LLM 模型"),
    ("scheduler.interval_minutes", "5", "定时任务执行间隔"),
    ("scheduler.batch_size", "100", "单次任务最大处理文件数"),
    ("scheduler.max_retries", "3", "可重试错误最大重试次数"),
    ("scheduler.retry_interval_minutes", "30", "失败后再次重试间隔"),
    ("scheduler.processing_timeout_minutes", "30", "processing 超时回收阈值"),
    ("scheduler.status", "idle", "调度器状态"),
    ("scheduler.last_run", "", "上次执行时间戳"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "files",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("file_ext", sa.String(length=20), nullable=True),
        sa.Column("index_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_files_status", "files", ["index_status"])
    op.create_index("idx_files_retry", "files", ["index_status", "next_retry_at"])
    op.create_index("idx_files_created", "files", ["created_at"])

    op.create_table(
        "file_segments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("file_id", sa.String(length=36), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("location_type", sa.String(length=30), nullable=False),
        sa.Column("location_value", sa.String(length=100), nullable=False),
        sa.Column("location_start", sa.Integer(), nullable=True),
        sa.Column("location_end", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_segments_file_id", "file_segments", ["file_id"])
    op.create_index("idx_segments_status", "file_segments", ["status"])

    op.create_table(
        "system_configs",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "scheduler_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
    )
    op.create_index("idx_scheduler_logs_started", "scheduler_logs", ["started_at"])

    system_configs = sa.table(
        "system_configs",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        system_configs,
        [
            {"key": key, "value": value, "description": description}
            for key, value, description in DEFAULT_CONFIGS
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_scheduler_logs_started", table_name="scheduler_logs")
    op.drop_table("scheduler_logs")
    op.drop_table("system_configs")
    op.drop_index("idx_segments_status", table_name="file_segments")
    op.drop_index("idx_segments_file_id", table_name="file_segments")
    op.drop_table("file_segments")
    op.drop_index("idx_files_created", table_name="files")
    op.drop_index("idx_files_retry", table_name="files")
    op.drop_index("idx_files_status", table_name="files")
    op.drop_table("files")
