from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.core.errors import AppError, ErrorCode
from app.core.schemas import (
    FileDeleteResponse,
    FileGraphResponse,
    FileInfo,
    FileListResponse,
    FileUpdateRequest,
)
from app.db.session import get_session
from app.infrastructure.lightrag_graph import LightRAGGraphReader
from app.infrastructure.index_progress import get_progress
from app.models.file import File, FileStatus
from app.models.file_segment import FileSegment
from app.models.scheduler_log import SchedulerLog
from app.services.file_service import FileService

router = APIRouter(prefix="/files", tags=["files"])


def to_file_info(file_record: File, segment_count: int | None = None) -> FileInfo:
    progress = _file_progress(file_record)
    return FileInfo(
        file_id=file_record.id,
        folder_id=file_record.folder_id,
        folder_name=file_record.folder.name if file_record.folder else None,
        filename=file_record.filename,
        size=file_record.file_size_bytes,
        content_type=file_record.content_type,
        file_ext=file_record.file_ext,
        index_status=file_record.index_status,
        error_code=file_record.error_code,
        error_msg=file_record.error_msg,
        retry_count=file_record.retry_count,
        next_retry_at=file_record.next_retry_at,
        segment_count=segment_count,
        progress_percent=progress["percent"],
        progress_stage=progress["stage"],
        progress_message=progress["message"],
        progress_processed_chunks=progress.get("processed_chunks"),
        progress_total_chunks=progress.get("total_chunks"),
        indexed_at=file_record.indexed_at,
        created_at=file_record.created_at,
    )


def _file_progress(file_record: File) -> dict:
    status = file_record.index_status
    if status == FileStatus.DELETING.value:
        return {"percent": 75, "stage": "deleting", "message": "Deleting"}
    if status == FileStatus.DELETED.value:
        return {"percent": 100, "stage": "deleted", "message": "Deleted"}

    if file_record.progress_percent is not None and status in {
        FileStatus.PENDING.value,
        FileStatus.PROCESSING.value,
        FileStatus.FAILED.value,
    }:
        return {
            "percent": file_record.progress_percent,
            "stage": file_record.progress_stage or status,
            "message": file_record.progress_message or status,
            "processed_chunks": file_record.progress_processed_chunks,
            "total_chunks": file_record.progress_total_chunks,
        }

    runtime = get_progress(file_record.id)
    if runtime is not None and file_record.index_status in {
        FileStatus.PENDING.value,
        FileStatus.PROCESSING.value,
        FileStatus.FAILED.value,
    }:
        return runtime

    if status == FileStatus.COMPLETED.value:
        return {"percent": 100, "stage": "completed", "message": "已完成"}
    if status == FileStatus.FAILED.value:
        return {"percent": 100, "stage": "failed", "message": "失败"}
    if status == FileStatus.DELETING.value:
        return {"percent": 75, "stage": "deleting", "message": "清理中"}
    if status == FileStatus.DELETED.value:
        return {"percent": 100, "stage": "deleted", "message": "已删除"}
    if status == FileStatus.PROCESSING.value:
        return {"percent": 15, "stage": "processing", "message": "处理中"}
    if status == FileStatus.PENDING.value:
        return {"percent": 5, "stage": "pending", "message": "等待调度"}
    return {"percent": 0, "stage": status or "unknown", "message": status or "-"}


@router.get("", response_model=FileListResponse)
async def list_files(
    status: str | None = None,
    folder_id: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> FileListResponse:
    service = FileService(session)
    items, total = await service.list(
        status=status,
        folder_id=folder_id,
        q=q,
        limit=limit,
        offset=offset,
    )
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


@router.patch("/{file_id}", response_model=FileInfo)
async def update_file(
    file_id: str,
    payload: FileUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> FileInfo:
    service = FileService(session)
    file_record = await service.move(file_id, payload.folder_id)
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


@router.get("/{file_id}/graph", response_model=FileGraphResponse)
async def file_graph(
    file_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileGraphResponse:
    file_record = await FileService(session).get(file_id)
    if file_record.index_status != FileStatus.COMPLETED.value:
        return FileGraphResponse(file_id=file_id, nodes=[], edges=[])
    nodes, edges = LightRAGGraphReader().read_file_graph(file_id)
    return FileGraphResponse(file_id=file_id, nodes=nodes, edges=edges)


@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileDeleteResponse:
    file_record = await FileService(session).mark_deleted(file_id)
    session.add(
        SchedulerLog(
            id=str(uuid4()),
            trigger_type="delete",
            status="success",
            total_files=1,
            processed_files=0,
            failed_files=0,
            skipped_files=0,
            details={"file_id": file_record.id, "filename": file_record.filename},
        )
    )
    await session.commit()
    return FileDeleteResponse(
        success=True,
        file_id=file_record.id,
        index_status=file_record.index_status,
        message="文件已从检索结果中隐藏，后台定时任务将清理索引和原文件",
    )
