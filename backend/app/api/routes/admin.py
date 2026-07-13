from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.schemas import (
    AdminStatusResponse,
    ConfigItem,
    ConfigUpdateRequest,
    FileInfo,
    SchedulerLogInfo,
    SchedulerLogsResponse,
    SchedulerTriggerResponse,
)
from app.db.session import get_session
from app.models.file import File
from app.models.file_segment import FileSegment
from app.models.scheduler_log import SchedulerLog
from app.models.system_config import SystemConfig
from app.api.routes.files import to_file_info
from app.scheduler.index_job import scheduler_status
from app.services.file_service import FileService
from app.worker.indexer import request_manual_trigger

router = APIRouter(prefix="/admin", tags=["admin"])


CONFIG_SPECS = {
    "rag.default_top_k": {
        "description": "检索默认返回片段数；影响后续检索请求",
        "value_type": "int",
        "min_value": 1,
        "max_value": 50,
        "default": "5",
        "effective_scope": "future_retrieve",
    },
    "rag.search_mode": {
        "description": "LightRAG 检索模式；影响后续检索请求",
        "value_type": "enum",
        "enum_values": ["naive", "local", "global", "hybrid", "mix"],
        "default": "global",
        "effective_scope": "future_retrieve",
    },
    "rag.chunk_size": {
        "description": "应用层分片大小，单位 tokens；只影响新索引文件",
        "value_type": "int",
        "min_value": 128,
        "max_value": 8192,
        "default": "1024",
        "effective_scope": "new_files_only",
    },
    "rag.chunk_overlap": {
        "description": "应用层分片重叠，单位 tokens；必须小于 chunk_size，只影响新索引文件",
        "value_type": "int",
        "min_value": 0,
        "max_value": 2048,
        "default": "200",
        "effective_scope": "new_files_only",
    },
    "scheduler.batch_size": {
        "description": "单次调度最多处理文件数；影响后续调度",
        "value_type": "int",
        "min_value": 1,
        "max_value": 500,
        "default": "100",
        "effective_scope": "future_scheduler_runs",
    },
    "scheduler.max_retries": {
        "description": "可重试失败的最大自动重试次数；影响后续失败处理",
        "value_type": "int",
        "min_value": 0,
        "max_value": 10,
        "default": "3",
        "effective_scope": "future_retry_decisions",
    },
    "scheduler.retry_interval_minutes": {
        "description": "可重试失败再次入队间隔，单位分钟；影响后续失败处理",
        "value_type": "int",
        "min_value": 1,
        "max_value": 1440,
        "default": "30",
        "effective_scope": "future_retry_decisions",
    },
    "scheduler.processing_timeout_minutes": {
        "description": "processing 状态超时回收阈值，单位分钟；影响后续调度",
        "value_type": "int",
        "min_value": 1,
        "max_value": 1440,
        "default": "30",
        "effective_scope": "future_scheduler_runs",
    },
}


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
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key.in_(CONFIG_SPECS)).order_by(SystemConfig.key)
    )
    by_key = {item.key: item for item in result.scalars().all()}
    return [_config_item(key, by_key.get(key)) for key in CONFIG_SPECS]


@router.put("/configs", response_model=list[ConfigItem])
async def update_configs(
    request: ConfigUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> list[ConfigItem]:
    changed_keys: list[str] = []
    for key, value in request.configs.items():
        _validate_config_value(key, value, request.configs)
        item = await session.get(SystemConfig, key)
        if item is None:
            item = SystemConfig(
                key=key,
                value=value,
                description=CONFIG_SPECS[key]["description"],
            )
            session.add(item)
            changed_keys.append(key)
        else:
            if item.value != value:
                changed_keys.append(key)
            item.value = value
            item.description = CONFIG_SPECS[key]["description"]
    if changed_keys:
        session.add(
            SchedulerLog(
                id=str(uuid4()),
                trigger_type="config",
                status="success",
                total_files=0,
                processed_files=0,
                failed_files=0,
                skipped_files=0,
                details={"changed_keys": sorted(changed_keys)},
            )
        )
    await session.commit()
    return await list_configs(session)


@router.get("/scheduler/status")
async def get_scheduler_status() -> dict[str, object]:
    return scheduler_status()


@router.post("/scheduler/trigger", response_model=SchedulerTriggerResponse)
async def trigger_scheduler(
    session: AsyncSession = Depends(get_session),
) -> SchedulerTriggerResponse:
    requested_at = await request_manual_trigger(session)
    log = SchedulerLog(
        id=str(uuid4()),
        trigger_type="manual_signal",
        status="accepted",
        total_files=0,
        processed_files=0,
        failed_files=0,
        skipped_files=0,
        details={"requested_at": requested_at},
    )
    session.add(log)
    await session.commit()
    return SchedulerTriggerResponse(
        success=True,
        log_id=log.id,
        status="accepted",
        message="Manual index trigger accepted by worker queue",
    )


@router.post("/files/{file_id}/retry", response_model=FileInfo)
async def retry_failed_file(
    file_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileInfo:
    service = FileService(session)
    file_record = await service.retry_failed(file_id)
    session.add(
        SchedulerLog(
            id=str(uuid4()),
            trigger_type="retry",
            status="success",
            total_files=1,
            processed_files=0,
            failed_files=0,
            skipped_files=0,
            details={"file_id": file_id, "filename": file_record.filename},
        )
    )
    await session.commit()
    return to_file_info(
        file_record,
        segment_count=await service.segment_count(file_id),
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


def _config_item(key: str, item: SystemConfig | None) -> ConfigItem:
    spec = CONFIG_SPECS[key]
    return ConfigItem(
        key=key,
        value=item.value if item is not None else str(spec["default"]),
        description=str(spec["description"]),
        value_type=str(spec["value_type"]),
        min_value=spec.get("min_value"),
        max_value=spec.get("max_value"),
        enum_values=spec.get("enum_values"),
        effective_scope=str(spec["effective_scope"]),
    )


def _validate_config_value(
    key: str,
    value: str,
    payload: dict[str, str],
) -> None:
    spec = CONFIG_SPECS.get(key)
    if spec is None:
        raise AppError(
            f"Config is not editable: {key}",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        )

    if spec["value_type"] == "enum":
        allowed = set(spec["enum_values"])
        if value not in allowed:
            raise AppError(
                f"{key} must be one of: {', '.join(sorted(allowed))}",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
        return

    if spec["value_type"] != "int":
        return

    try:
        parsed = int(value)
    except ValueError as exc:
        raise AppError(
            f"{key} must be an integer",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        ) from exc

    min_value = int(spec["min_value"])
    max_value = int(spec["max_value"])
    if parsed < min_value or parsed > max_value:
        raise AppError(
            f"{key} must be between {min_value} and {max_value}",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
        )

    if key == "rag.chunk_overlap":
        chunk_size = int(payload.get("rag.chunk_size", CONFIG_SPECS["rag.chunk_size"]["default"]))
        if parsed >= chunk_size:
            raise AppError(
                "rag.chunk_overlap must be smaller than rag.chunk_size",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=422,
            )
