from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.models.file import File, FileStatus
from app.models.file_segment import FileSegment, SegmentStatus
from app.services.folder_service import FolderService


class FileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upload(self, upload_file: UploadFile, folder_id: str | None = None) -> File:
        filename = Path(upload_file.filename or "").name
        if not filename:
            raise AppError("Filename is required", code=ErrorCode.FILE_TYPE_NOT_ALLOWED, status_code=415)

        ext = Path(filename).suffix.lower()
        if ext not in settings.allowed_extensions:
            raise AppError(
                f"Unsupported file type: {ext}",
                code=ErrorCode.FILE_TYPE_NOT_ALLOWED,
                status_code=415,
            )

        content = await upload_file.read()
        if not content:
            raise AppError("Uploaded file is empty", code=ErrorCode.EMPTY_CONTENT, status_code=422)

        max_size = settings.max_upload_size_mb * 1024 * 1024
        if len(content) > max_size:
            raise AppError(
                f"File exceeds {settings.max_upload_size_mb}MB limit",
                code=ErrorCode.FILE_TOO_LARGE,
                status_code=413,
            )

        file_id = f"f_{uuid4().hex}"
        folder = await FolderService(self.session).get(folder_id)
        await self._ensure_unique_filename(filename, folder_id=folder.id)
        upload_dir = Path(settings.upload_dir)
        if not upload_dir.is_absolute():
            upload_dir = Path(__file__).resolve().parents[3] / upload_dir
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / f"{file_id}_{filename}"
        file_path.write_bytes(content)

        file_record = File(
            id=file_id,
            folder_id=folder.id,
            filename=filename,
            file_path=str(file_path),
            file_size_bytes=len(content),
            content_type=upload_file.content_type,
            file_ext=ext,
            index_status=FileStatus.PENDING.value,
        )
        self.session.add(file_record)
        await self.session.commit()
        await self.session.refresh(file_record)
        return file_record

    async def get(self, file_id: str, include_deleted: bool = False) -> File:
        stmt = select(File).options(selectinload(File.folder)).where(File.id == file_id)
        if not include_deleted:
            stmt = stmt.where(File.index_status != FileStatus.DELETED.value)
        file_record = await self.session.scalar(stmt)
        if file_record is None:
            raise AppError("File not found", code=ErrorCode.FILE_NOT_FOUND, status_code=404)
        return file_record

    async def list(
        self,
        *,
        status: str | None = None,
        folder_id: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[File], int]:
        filters = [File.index_status != FileStatus.DELETED.value]
        if status:
            filters.append(File.index_status == status)
        if folder_id:
            await FolderService(self.session).get(folder_id)
            filters.append(File.folder_id == folder_id)
        if q:
            filters.append(File.filename.ilike(f"%{q.strip()}%"))

        total_stmt = select(func.count()).select_from(File).where(*filters)
        total = await self.session.scalar(total_stmt)

        stmt: Select[tuple[File]] = (
            select(File)
            .options(selectinload(File.folder))
            .where(*filters)
            .order_by(File.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self.session.scalars(stmt)
        return list(rows), int(total or 0)

    async def move(self, file_id: str, folder_id: str | None) -> File:
        file_record = await self.get(file_id)
        folder = await FolderService(self.session).get(folder_id)
        if file_record.folder_id != folder.id:
            await self._ensure_unique_filename(
                file_record.filename,
                folder_id=folder.id,
                exclude_file_id=file_record.id,
            )
        file_record.folder_id = folder.id
        await self.session.commit()
        return await self.get(file_id)

    async def mark_deleted(self, file_id: str) -> File:
        file_record = await self.get(file_id)
        file_record.index_status = FileStatus.DELETING.value
        file_record.deleted_at = datetime.now(timezone.utc)

        segments = await self.session.scalars(
            select(FileSegment).where(FileSegment.file_id == file_id)
        )
        for segment in segments:
            segment.status = SegmentStatus.DELETED.value

        await self.session.commit()
        await self.session.refresh(file_record)
        return file_record

    async def retry_failed(self, file_id: str) -> File:
        file_record = await self.get(file_id)
        if file_record.index_status != FileStatus.FAILED.value:
            raise AppError(
                "Only failed files can be retried",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=409,
            )

        file_record.index_status = FileStatus.PENDING.value
        file_record.retry_count = 0
        file_record.next_retry_at = datetime.now(timezone.utc)
        file_record.processing_started_at = None
        file_record.error_code = None
        file_record.error_msg = None

        segments = await self.session.scalars(
            select(FileSegment).where(FileSegment.file_id == file_id)
        )
        for segment in segments:
            if segment.status != SegmentStatus.DELETED.value:
                segment.status = SegmentStatus.PENDING.value

        await self.session.commit()
        await self.session.refresh(file_record)
        return file_record

    async def segment_count(self, file_id: str) -> int:
        count = await self.session.scalar(
            select(func.count()).select_from(FileSegment).where(FileSegment.file_id == file_id)
        )
        return int(count or 0)

    async def _ensure_unique_filename(
        self,
        filename: str,
        *,
        folder_id: str,
        exclude_file_id: str | None = None,
    ) -> None:
        stmt = select(File.id).where(
            File.folder_id == folder_id,
            func.lower(File.filename) == filename.lower(),
            File.index_status.not_in(
                [FileStatus.DELETED.value, FileStatus.DELETING.value]
            ),
        )
        if exclude_file_id is not None:
            stmt = stmt.where(File.id != exclude_file_id)
        existing = await self.session.scalar(stmt.limit(1))
        if existing is not None:
            raise AppError(
                "A file with the same name already exists in this folder",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=409,
            )
