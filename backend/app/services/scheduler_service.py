from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.config import settings
from app.db.session import engine
from app.core.errors import AppError, ErrorCode
from app.infrastructure.lightrag_client import LightRAGClient
from app.models.file import File, FileStatus
from app.models.file_segment import FileSegment, SegmentStatus
from app.models.scheduler_log import SchedulerLog
from app.models.system_config import SystemConfig
from app.services.segment_service import SegmentService

LOCK_NAME = "rag_platform_index_scheduler"
NON_RETRYABLE_CODES = {
    ErrorCode.FILE_TOO_LARGE.value,
    ErrorCode.FILE_TYPE_NOT_ALLOWED.value,
    ErrorCode.EMPTY_CONTENT.value,
    ErrorCode.PARSE_ENCRYPTED_PDF.value,
}


@dataclass(frozen=True)
class SchedulerRunResult:
    started: bool
    log_id: str
    status: str
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    message: str = ""


class SchedulerService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        lightrag_client: LightRAGClient | None = None,
    ) -> None:
        self.session = session
        self._lightrag_client = lightrag_client
        self._lock_connection: AsyncConnection | None = None

    @property
    def lightrag_client(self) -> LightRAGClient:
        if self._lightrag_client is None:
            self._lightrag_client = LightRAGClient()
        return self._lightrag_client

    async def run_once(self, *, trigger_type: str) -> SchedulerRunResult:
        log = SchedulerLog(
            id=str(uuid4()),
            trigger_type=trigger_type,
            status="running",
            total_files=0,
            processed_files=0,
            failed_files=0,
            skipped_files=0,
            details={},
        )
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)

        lock_acquired = await self._try_lock()
        if not lock_acquired:
            log.status = "skipped"
            log.finished_at = self._now()
            log.error_msg = "Scheduler is already running"
            await self.session.commit()
            return SchedulerRunResult(
                started=False,
                log_id=log.id,
                status=log.status,
                message=log.error_msg or "",
            )

        processed = 0
        failed = 0
        skipped = 0
        details: dict[str, Any] = {"files": []}

        try:
            recycled = await self.recycle_processing_timeouts()
            deleted = await self.cleanup_deleting_files()
            files = await self._load_pending_files()
            log.total_files = len(files)
            log.details = {
                "recycled_processing": recycled,
                "deleted_files": deleted,
                "files": [],
            }
            await self.session.commit()

            for file_record in files:
                try:
                    await self._process_file(file_record)
                    processed += 1
                    details["files"].append(
                        {"file_id": file_record.id, "status": "completed"}
                    )
                except AppError as exc:
                    failed += 1
                    details["files"].append(
                        {
                            "file_id": file_record.id,
                            "status": "failed",
                            "error_code": exc.code.value,
                            "error_msg": exc.detail,
                        }
                    )
                except Exception as exc:
                    failed += 1
                    await self._mark_retryable_failure(
                        file_record,
                        error_code="LIGHTRAG_INDEX_ERROR",
                        error_msg=str(exc),
                    )
                    details["files"].append(
                        {
                            "file_id": file_record.id,
                            "status": "failed",
                            "error_code": "LIGHTRAG_INDEX_ERROR",
                            "error_msg": str(exc),
                        }
                    )

            log.status = "success" if failed == 0 else "partial_failed"
            return SchedulerRunResult(
                started=True,
                log_id=log.id,
                status=log.status,
                total_files=len(files),
                processed_files=processed,
                failed_files=failed,
                skipped_files=skipped,
                message="Scheduler run completed",
            )
        except Exception as exc:
            log.status = "failed"
            log.error_msg = str(exc)
            return SchedulerRunResult(
                started=True,
                log_id=log.id,
                status=log.status,
                total_files=log.total_files,
                processed_files=processed,
                failed_files=failed,
                skipped_files=skipped,
                message=str(exc),
            )
        finally:
            if self._lightrag_client is not None and hasattr(
                self._lightrag_client, "finalize"
            ):
                await self.lightrag_client.finalize()
            log.processed_files = processed
            log.failed_files = failed
            log.skipped_files = skipped
            log.finished_at = self._now()
            log.details = {**(log.details or {}), **details}
            await self.session.commit()
            await self._unlock()

    async def recycle_processing_timeouts(self) -> int:
        timeout_minutes = await self._int_config(
            "scheduler.processing_timeout_minutes",
            settings.scheduler_processing_timeout_minutes,
        )
        max_retries = await self._int_config(
            "scheduler.max_retries",
            settings.scheduler_max_retries,
        )
        cutoff = self._now() - timedelta(minutes=timeout_minutes)

        result = await self.session.execute(
            select(File).where(
                File.index_status == FileStatus.PROCESSING.value,
                File.processing_started_at < cutoff,
            )
        )
        files = list(result.scalars().all())
        for file_record in files:
            file_record.retry_count += 1
            file_record.processing_started_at = None
            file_record.error_code = "PROCESSING_TIMEOUT"
            file_record.error_msg = "Indexing exceeded processing timeout"
            if file_record.retry_count < max_retries:
                file_record.index_status = FileStatus.PENDING.value
                file_record.next_retry_at = self._now()
            else:
                file_record.index_status = FileStatus.FAILED.value
                file_record.next_retry_at = None
        if files:
            await self.session.commit()
        return len(files)

    async def cleanup_deleting_files(self) -> int:
        result = await self.session.execute(
            select(File)
            .where(File.index_status == FileStatus.DELETING.value)
            .order_by(File.deleted_at, File.created_at)
            .limit(settings.scheduler_batch_size)
        )
        files = list(result.scalars().all())
        cleaned = 0

        for file_record in files:
            try:
                await self.lightrag_client.delete_file(file_record.id)
            except Exception:
                continue
            file_record.index_status = FileStatus.DELETED.value
            file_record.deleted_at = self._now()
            cleaned += 1

        if cleaned:
            await self.session.commit()
        return cleaned

    async def _process_file(self, file_record: File) -> None:
        chunk_size = await self._int_config("rag.chunk_size", 1024)
        chunk_overlap = await self._int_config("rag.chunk_overlap", 200)

        file_record.index_status = FileStatus.PROCESSING.value
        file_record.processing_started_at = self._now()
        file_record.error_code = None
        file_record.error_msg = None
        await self.session.commit()

        try:
            segments = await SegmentService(self.session).parse_and_store(
                file_record,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        except AppError as exc:
            if exc.code.value in NON_RETRYABLE_CODES:
                file_record.next_retry_at = None
                file_record.processing_started_at = None
                await self.session.commit()
            raise

        await self.lightrag_client.insert_segments(
            file_id=file_record.id,
            filename=file_record.filename,
            segments=segments,
        )

        for segment in segments:
            segment.status = SegmentStatus.INDEXED.value
        file_record.index_status = FileStatus.COMPLETED.value
        file_record.indexed_at = self._now()
        file_record.processing_started_at = None
        file_record.error_code = None
        file_record.error_msg = None
        file_record.next_retry_at = None
        await self.session.commit()

    async def _mark_retryable_failure(
        self,
        file_record: File,
        *,
        error_code: str,
        error_msg: str,
    ) -> None:
        await self.session.rollback()
        max_retries = await self._int_config(
            "scheduler.max_retries", settings.scheduler_max_retries
        )
        retry_interval = await self._int_config(
            "scheduler.retry_interval_minutes",
            settings.scheduler_retry_interval_minutes,
        )
        file_record = await self.session.get(File, file_record.id)
        if file_record is None:
            return

        file_record.retry_count += 1
        file_record.index_status = FileStatus.FAILED.value
        file_record.processing_started_at = None
        file_record.error_code = error_code
        file_record.error_msg = error_msg
        if file_record.retry_count < max_retries:
            file_record.next_retry_at = self._now() + timedelta(minutes=retry_interval)
        else:
            file_record.next_retry_at = None
        await self.session.commit()

    async def _load_pending_files(self) -> list[File]:
        batch_size = await self._int_config(
            "scheduler.batch_size", settings.scheduler_batch_size
        )
        now = self._now()
        stmt = (
            select(File)
            .where(
                or_(
                    File.index_status == FileStatus.PENDING.value,
                    (
                        (File.index_status == FileStatus.FAILED.value)
                        & (File.next_retry_at.is_not(None))
                        & (File.next_retry_at <= now)
                    ),
                )
            )
            .order_by(File.created_at)
            .limit(batch_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _try_lock(self) -> bool:
        self._lock_connection = await engine.connect()
        result = await self._lock_connection.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:lock_name))"),
            {"lock_name": LOCK_NAME},
        )
        acquired = bool(result.scalar_one())
        if not acquired:
            await self._lock_connection.close()
            self._lock_connection = None
        return acquired

    async def _unlock(self) -> None:
        if self._lock_connection is None:
            return
        try:
            await self._lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_name))"),
                {"lock_name": LOCK_NAME},
            )
            await self._lock_connection.commit()
        finally:
            await self._lock_connection.close()
            self._lock_connection = None

    async def _int_config(self, key: str, default: int) -> int:
        value = await self._config_value(key)
        if value in {None, ""}:
            return default
        return int(value)

    async def _config_value(self, key: str) -> str | None:
        result = await self.session.execute(
            select(SystemConfig.value).where(SystemConfig.key == key)
        )
        return result.scalar_one_or_none()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
