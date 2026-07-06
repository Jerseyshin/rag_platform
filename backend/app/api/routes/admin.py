import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import (
    AdminStatusResponse,
    ConfigItem,
    ConfigUpdateRequest,
    SchedulerLogInfo,
    SchedulerLogsResponse,
    SchedulerTriggerResponse,
)
from app.db.session import get_session
from app.models.file import File
from app.models.file_segment import FileSegment
from app.models.scheduler_log import SchedulerLog
from app.models.system_config import SystemConfig
from app.scheduler.index_job import run_index_job
from app.scheduler.index_job import scheduler_status

router = APIRouter(prefix="/admin", tags=["admin"])


def _consume_task_exception(task: asyncio.Task) -> None:
    try:
        task.result()
    except Exception:
        # SchedulerService records run failures in scheduler_logs when possible.
        # This callback only prevents an unobserved background task exception.
        pass


@router.get("/status", response_model=AdminStatusResponse)
async def admin_status(
    session: AsyncSession = Depends(get_session),
) -> AdminStatusResponse:
    file_counts = await _group_counts(session, File.index_status)
    segment_counts = await _group_counts(session, FileSegment.status)
    return AdminStatusResponse(
        files=file_counts,
        segments=segment_counts,
        scheduler=scheduler_status(),
    )


@router.get("/configs", response_model=list[ConfigItem])
async def list_configs(
    session: AsyncSession = Depends(get_session),
) -> list[ConfigItem]:
    result = await session.execute(select(SystemConfig).order_by(SystemConfig.key))
    return [
        ConfigItem(key=item.key, value=item.value, description=item.description)
        for item in result.scalars().all()
    ]


@router.put("/configs", response_model=list[ConfigItem])
async def update_configs(
    request: ConfigUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> list[ConfigItem]:
    for key, value in request.configs.items():
        item = await session.get(SystemConfig, key)
        if item is None:
            item = SystemConfig(key=key, value=value, description=None)
            session.add(item)
        else:
            item.value = value
    await session.commit()
    return await list_configs(session)


@router.get("/scheduler/status")
async def get_scheduler_status() -> dict[str, object]:
    return scheduler_status()


@router.post("/scheduler/trigger", response_model=SchedulerTriggerResponse)
async def trigger_scheduler() -> SchedulerTriggerResponse:
    task = asyncio.create_task(run_index_job(trigger_type="manual"))
    task.add_done_callback(_consume_task_exception)
    return SchedulerTriggerResponse(
        success=True,
        log_id="",
        status="accepted",
        message="Scheduler run accepted",
    )


@router.get("/scheduler/logs", response_model=SchedulerLogsResponse)
async def scheduler_logs(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SchedulerLogsResponse:
    total = (
        await session.execute(select(func.count()).select_from(SchedulerLog))
    ).scalar_one()
    result = await session.execute(
        select(SchedulerLog)
        .order_by(SchedulerLog.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        SchedulerLogInfo(
            id=item.id,
            trigger_type=item.trigger_type,
            started_at=item.started_at,
            finished_at=item.finished_at,
            status=item.status,
            total_files=item.total_files,
            processed_files=item.processed_files,
            failed_files=item.failed_files,
            skipped_files=item.skipped_files,
            error_msg=item.error_msg,
            details=item.details,
        )
        for item in result.scalars().all()
    ]
    return SchedulerLogsResponse(items=items, total=total, limit=limit, offset=offset)


async def _group_counts(session: AsyncSession, column) -> dict[str, int]:
    result = await session.execute(select(column, func.count()).group_by(column))
    return {str(key): int(value) for key, value in result.all()}
