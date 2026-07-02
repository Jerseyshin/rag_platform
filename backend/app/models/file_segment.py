from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.session import Base


class SegmentStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    DELETED = "deleted"


class LocationType(StrEnum):
    PAGE = "page"
    PARAGRAPH = "paragraph"
    CHUNK = "chunk"


class FileSegment(Base):
    __tablename__ = "file_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    location_type: Mapped[str] = mapped_column(String(30), nullable=False)
    location_value: Mapped[str] = mapped_column(String(100), nullable=False)
    location_start: Mapped[int | None] = mapped_column(Integer)
    location_end: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SegmentStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    file: Mapped["File"] = relationship(back_populates="segments")

