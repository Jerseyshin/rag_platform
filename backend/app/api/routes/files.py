from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.schemas import FileDeleteResponse, FileInfo, FileListResponse
from app.db.session import get_session
from app.models.file import File, FileStatus
from app.models.file_segment import FileSegment
from app.services.file_service import FileService

router = APIRouter(prefix="/files", tags=["files"])


def to_file_info(file_record: File, segment_count: int | None = None) -> FileInfo:
    return FileInfo(
        file_id=file_record.id,
        filename=file_record.filename,
        size=file_record.file_size_bytes,
        content_type=file_record.content_type,
        file_ext=file_record.file_ext,
        index_status=file_record.index_status,
        error_code=file_record.error_code,
        error_msg=file_record.error_msg,
        retry_count=file_record.retry_count,
        segment_count=segment_count,
        indexed_at=file_record.indexed_at,
        created_at=file_record.created_at,
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> FileListResponse:
    service = FileService(session)
    items, total = await service.list(status=status, limit=limit, offset=offset)
    file_ids = [item.id for item in items]
    seg_counts: dict[str, int] = {}
    if file_ids:
        rows = await session.execute(
            select(FileSegment.file_id, func.count(FileSegment.id))
            .where(FileSegment.file_id.in_(file_ids))
            .group_by(FileSegment.file_id)
        )
        seg_counts = {file_id: int(count) for file_id, count in rows.all()}

    return FileListResponse(
        items=[
            to_file_info(item, segment_count=seg_counts.get(item.id, 0))
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{file_id}", response_model=FileInfo)
async def get_file(
    file_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileInfo:
    service = FileService(session)
    file_record = await service.get(file_id)
    return to_file_info(file_record, segment_count=await service.segment_count(file_id))


@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    file_record = await FileService(session).get(file_id)
    if file_record.index_status in {
        FileStatus.DELETING.value,
        FileStatus.DELETED.value,
    }:
        raise AppError(
            "File not found",
            code=ErrorCode.FILE_NOT_FOUND,
            status_code=404,
        )
    return FileResponse(path=file_record.file_path, filename=file_record.filename)


@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileDeleteResponse:
    file_record = await FileService(session).mark_deleted(file_id)
    return FileDeleteResponse(
        success=True,
        file_id=file_record.id,
        index_status=file_record.index_status,
        message="文件已从检索结果中隐藏，后台将异步清理索引",
    )
