from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone


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
    _progress[file_id] = IndexProgress(
        percent=max(0, min(100, int(percent))),
        stage=stage,
        message=message,
        processed_chunks=processed_chunks,
        total_chunks=total_chunks,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def start_lightrag_progress(file_id: str, *, total_chunks: int) -> None:
    set_progress(
        file_id,
        percent=20,
        stage="indexing",
        message=f"LightRAG indexing 0/{total_chunks}",
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
        message=f"LightRAG indexing {processed}/{total}",
        processed_chunks=processed,
        total_chunks=total,
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
