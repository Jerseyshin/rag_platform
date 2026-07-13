from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.scheduler_service import SchedulerService

_scheduler: AsyncIOScheduler | None = None


async def run_index_job(trigger_type: str = "scheduled") -> None:
    async with AsyncSessionLocal() as session:
        await SchedulerService(session).run_once(trigger_type=trigger_type)


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.scheduler_enabled:
        return None
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_index_job,
        trigger=IntervalTrigger(minutes=settings.scheduler_interval_minutes),
        id="rag_index_job",
        kwargs={"trigger_type": "scheduled"},
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def scheduler_status() -> dict[str, object]:
    mode = "in_api" if settings.run_indexer_in_api else "external_worker"
    if _scheduler is None:
        return {
            "enabled": settings.scheduler_enabled,
            "running": False,
            "mode": mode,
            "jobs": [],
        }

    return {
        "enabled": settings.scheduler_enabled,
        "running": _scheduler.running,
        "mode": mode,
        "jobs": [
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat()
                if job.next_run_time
                else None,
            }
            for job in _scheduler.get_jobs()
        ],
    }
