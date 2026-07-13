from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.session import Base


class FileStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    folder_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    file_ext: Mapped[str | None] = mapped_column(String(20))
    index_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FileStatus.PENDING.value
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_msg: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    progress_percent: Mapped[int | None] = mapped_column(Integer)
    progress_stage: Mapped[str | None] = mapped_column(String(50))
    progress_message: Mapped[str | None] = mapped_column(Text)
    progress_processed_chunks: Mapped[int | None] = mapped_column(Integer)
    progress_total_chunks: Mapped[int | None] = mapped_column(Integer)
    progress_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    segments: Mapped[list["FileSegment"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
    folder: Mapped["Folder | None"] = relationship(back_populates="files")
