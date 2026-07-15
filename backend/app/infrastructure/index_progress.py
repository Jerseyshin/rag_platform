from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import logging
import re

from app.db.session import AsyncSessionLocal
from app.models.file import File


LIGHTRAG_CHUNK_LOG_PATTERN = re.compile(
    r"Chunk\s+(?P<processed>\d+)\s+of\s+(?P<total>\d+)\s+extracted\s+"
    r"(?P<entities>\d+)\s+Ent\s+\+\s+(?P<relations>\d+)\s+Rel\s+"
    r"(?P<chunk_id>\S+)"
)
logger = logging.getLogger(__name__)


@dataclass
class IndexProgress:
    percent: int
    stage: str
    message: str
    processed_chunks: int | None = None
    total_chunks: int | None = None
    updated_at: str | None = None


_progress: dict[str, IndexProgress] = {}


def set_progress(
    file_id: str,
    *,
    percent: int,
    stage: str,
    message: str,
    processed_chunks: int | None = None,
    total_chunks: int | None = None,
) -> None:
    item = IndexProgress(
        percent=max(0, min(100, int(percent))),
        stage=stage,
        message=message,
        processed_chunks=processed_chunks,
        total_chunks=total_chunks,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    _progress[file_id] = item
    _schedule_progress_persist(file_id, item)


def start_lightrag_progress(file_id: str, *, total_chunks: int) -> None:
    set_progress(
        file_id,
        percent=20,
        stage="indexing",
        message="LightRAG indexing",
        processed_chunks=0,
        total_chunks=total_chunks,
    )


def advance_lightrag_progress(file_id: str) -> None:
    current = _progress.get(file_id)
    if current is None:
        return
    total = current.total_chunks or 0
    if total <= 0:
        return

    processed = min((current.processed_chunks or 0) + 1, total)
    percent = 20 + round((processed / total) * 75)
    set_progress(
        file_id,
        percent=percent,
        stage="indexing",
        message="LightRAG indexing",
        processed_chunks=processed,
        total_chunks=total,
    )


def set_lightrag_chunk_progress(
    file_id: str,
    *,
    processed_chunks: int,
    total_chunks: int,
) -> None:
    if total_chunks <= 0:
        return
    processed = max(0, min(processed_chunks, total_chunks))
    percent = 20 + round((processed / total_chunks) * 75)
    set_progress(
        file_id,
        percent=percent,
        stage="indexing",
        message="LightRAG indexing",
        processed_chunks=processed,
        total_chunks=total_chunks,
    )


def record_lightrag_event(file_id: str, message: str) -> None:
    current = _progress.get(file_id)
    set_progress(
        file_id,
        percent=current.percent if current else 20,
        stage=current.stage if current else "indexing",
        message=message,
        processed_chunks=current.processed_chunks if current else None,
        total_chunks=current.total_chunks if current else None,
    )


def handle_lightrag_log_message(message: str) -> None:
    match = LIGHTRAG_CHUNK_LOG_PATTERN.search(message or "")
    if not match:
        return

    chunk_id = match.group("chunk_id")
    if "-chunk-" not in chunk_id:
        return
    file_id = chunk_id.rsplit("-chunk-", 1)[0]
    set_lightrag_chunk_progress(
        file_id,
        processed_chunks=int(match.group("processed")),
        total_chunks=int(match.group("total")),
    )


def complete_progress(file_id: str) -> None:
    set_progress(
        file_id,
        percent=100,
        stage="completed",
        message="Indexing completed",
    )


def fail_progress(file_id: str, message: str) -> None:
    set_progress(
        file_id,
        percent=100,
        stage="failed",
        message=message,
    )


def get_progress(file_id: str) -> dict | None:
    item = _progress.get(file_id)
    if item is None:
        return None
    return asdict(item)


def _schedule_progress_persist(file_id: str, item: IndexProgress) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_persist_progress(file_id, item))


async def _persist_progress(file_id: str, item: IndexProgress) -> None:
    try:
        updated_at = (
            datetime.fromisoformat(item.updated_at)
            if item.updated_at
            else datetime.now(timezone.utc)
        )
        async with AsyncSessionLocal() as session:
            file_record = await session.get(File, file_id)
            if file_record is None:
                return
            current_updated_at = file_record.progress_updated_at
            if (
                current_updated_at is not None
                and current_updated_at.tzinfo is None
            ):
                current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)
            if current_updated_at is not None and current_updated_at > updated_at:
                return
            file_record.progress_percent = item.percent
            file_record.progress_stage = item.stage
            file_record.progress_message = item.message
            file_record.progress_processed_chunks = item.processed_chunks
            file_record.progress_total_chunks = item.total_chunks
            file_record.progress_updated_at = updated_at
            await session.commit()
    except Exception:
        logger.exception("Failed to persist index progress file_id=%s", file_id)
