from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.system_config import SystemConfig
from app.services.scheduler_service import SchedulerService

MANUAL_TRIGGER_REQUESTED_KEY = "scheduler.manual_trigger_requested_at"
MANUAL_TRIGGER_CONSUMED_KEY = "scheduler.manual_trigger_consumed_at"

logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BACKEND_DIR / "logs"
LOG_FILE = LOG_DIR / "indexer_worker.log"


async def main() -> None:
    logger.info(
        "Indexer worker starting interval_minutes=%s poll_seconds=%s enabled=%s",
        settings.scheduler_interval_minutes,
        settings.indexer_worker_poll_seconds,
        settings.scheduler_enabled,
    )
    try:
        await worker_loop()
    finally:
        await engine.dispose()


async def worker_loop() -> None:
    next_scheduled_at = datetime.now(timezone.utc)
    while True:
        try:
            if not settings.scheduler_enabled:
                await asyncio.sleep(settings.indexer_worker_poll_seconds)
                continue

            async with AsyncSessionLocal() as session:
                requested_at = await _pending_manual_trigger(session)
                if requested_at is not None:
                    logger.info("Manual index trigger accepted requested_at=%s", requested_at)
                    result = await SchedulerService(session).run_once(trigger_type="manual")
                    if result.started:
                        await _mark_manual_trigger_consumed(session, requested_at)
                    continue

                now = datetime.now(timezone.utc)
                if now >= next_scheduled_at:
                    await SchedulerService(session).run_once(trigger_type="scheduled")
                    next_scheduled_at = now + timedelta(
                        minutes=settings.scheduler_interval_minutes
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Indexer worker loop failed")

        await asyncio.sleep(settings.indexer_worker_poll_seconds)


async def request_manual_trigger(session: AsyncSession) -> str:
    requested_at = datetime.now(timezone.utc).isoformat()
    await _upsert_config(
        session,
        MANUAL_TRIGGER_REQUESTED_KEY,
        requested_at,
        "Last requested manual index trigger time",
    )
    await session.commit()
    return requested_at


async def _pending_manual_trigger(session: AsyncSession) -> str | None:
    requested_at = await _config_value(session, MANUAL_TRIGGER_REQUESTED_KEY)
    if not requested_at:
        return None
    consumed_at = await _config_value(session, MANUAL_TRIGGER_CONSUMED_KEY)
    if consumed_at == requested_at:
        return None
    return requested_at


async def _mark_manual_trigger_consumed(
    session: AsyncSession,
    requested_at: str,
) -> None:
    await _upsert_config(
        session,
        MANUAL_TRIGGER_CONSUMED_KEY,
        requested_at,
        "Last consumed manual index trigger time",
    )
    await session.commit()


async def _config_value(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(select(SystemConfig.value).where(SystemConfig.key == key))
    return result.scalar_one_or_none()


async def _upsert_config(
    session: AsyncSession,
    key: str,
    value: str,
    description: str,
) -> None:
    item = await session.get(SystemConfig, key)
    if item is None:
        item = SystemConfig(key=key, value=value, description=description)
        session.add(item)
    else:
        item.value = value
        item.description = description


if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler, file_handler],
    )
    logger.info("Indexer worker log file: %s", LOG_FILE)
    asyncio.run(main())
