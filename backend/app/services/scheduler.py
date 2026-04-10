"""Scheduler service for periodic agent runs and maintenance tasks."""

from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import ScheduledJob
from app.services.jobs import (
    disable_agent_cadence_job,
    fill_missing_job_descriptions,
    get_job,
    list_jobs,
    record_job_run,
    seed_jobs_from_agent_cadence,
    upsert_agent_cadence_job,
)
from app.services.chat_sessions import prune_expired_session_archives
from app.services.memory import prune_old_data
from app.services.orchestrator import run_scheduled_agent
from app.services.prayer_service import auto_mark_unknown_expired, refresh_today_and_tomorrow_windows

logger = logging.getLogger(__name__)
ONCE_JOB_MISFIRE_GRACE_SECONDS = 600


def _new_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=settings.timezone)


scheduler = _new_scheduler()


def start_scheduler():
    global scheduler
    if not scheduler.running:
        try:
            scheduler.start()
        except RuntimeError as exc:
            # FastAPI TestClient can close/re-open loops between lifespan runs.
            if "Event loop is closed" in str(exc):
                scheduler = _new_scheduler()
                scheduler.start()
            else:
                raise
        logger.info("Scheduler started")


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def _parse_cadence(cron_expression: str) -> tuple[str, str, str]:
    parts = cron_expression.split()
    if len(parts) < 2:
        raise ValueError("Cadence must be at least 'minute hour'")
    minute = parts[0]
    hour = parts[1]
    day_of_week = parts[2] if len(parts) > 2 else "*"
    if len(parts) == 5:
        # Preserve compatibility for legacy tests while accepting full crontab input.
        minute = parts[0]
        hour = parts[1]
        day_of_week = parts[4]
    return minute, hour, day_of_week


def _scheduler_job_id(job_id: int) -> str:
    return f"scheduled_job_{job_id}"


def _to_db_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _to_scheduler_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _update_job_next_run(job_id: int, next_run: datetime | None) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(ScheduledJob).where(ScheduledJob.id == job_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        row.next_run_at = _to_db_datetime(next_run)
        await db.commit()


async def sync_persistent_job(job_id: int) -> None:
    row = await get_job(job_id)
    scheduler_id = _scheduler_job_id(job_id)
    existing = scheduler.get_job(scheduler_id)
    if not row:
        if existing:
            scheduler.remove_job(scheduler_id)
        return

    if not row.enabled or row.paused:
        if existing:
            scheduler.remove_job(scheduler_id)
        await _update_job_next_run(job_id, None)
        return

    trigger = None
    now_utc = datetime.now(timezone.utc)
    if row.schedule_type == "once":
        run_at = _to_scheduler_datetime(row.run_at)
        if not run_at:
            if existing:
                scheduler.remove_job(scheduler_id)
            await _update_job_next_run(job_id, None)
            return
        if row.completed_at:
            if existing:
                scheduler.remove_job(scheduler_id)
            await _update_job_next_run(job_id, None)
            return
        if now_utc > run_at + timedelta(seconds=ONCE_JOB_MISFIRE_GRACE_SECONDS):
            if existing:
                scheduler.remove_job(scheduler_id)
            await record_job_run(
                job_id=job_id,
                started_at=_to_db_datetime(now_utc) or datetime.now(timezone.utc).replace(tzinfo=None),
                finished_at=_to_db_datetime(now_utc) or datetime.now(timezone.utc).replace(tzinfo=None),
                status="missed",
                message="job_missed_startup_window",
                error=None,
                last_run_at=_to_db_datetime(now_utc),
                next_run_at=None,
                completed_at=_to_db_datetime(now_utc),
                enabled=False,
            )
            return
        trigger = DateTrigger(run_date=run_at, timezone=timezone.utc)
    else:
        trigger = CronTrigger.from_crontab(row.cron_expression, timezone=ZoneInfo(row.timezone))

    scheduler.add_job(
        run_persistent_job,
        trigger=trigger,
        id=scheduler_id,
        kwargs={"job_id": job_id},
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=ONCE_JOB_MISFIRE_GRACE_SECONDS,
    )
    scheduled = scheduler.get_job(scheduler_id)
    await _update_job_next_run(job_id, scheduled.next_run_time if scheduled else None)
    logger.info(
        "Scheduled persistent job id=%s name=%s type=%s schedule=%s tz=%s",
        row.id,
        row.name,
        row.schedule_type,
        row.cron_expression if row.schedule_type == "cron" else row.run_at,
        row.timezone,
    )


async def run_persistent_job(job_id: int) -> None:
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    status = "completed"
    message: str | None = None
    error: str | None = None
    row = None

    try:
        row = await get_job(job_id)
        if not row:
            status = "skipped"
            message = "job_not_found"
        elif not row.enabled or row.paused:
            status = "skipped"
            message = "job_disabled_or_paused"
        elif row.job_type == "agent_nudge":
            if not row.agent_name:
                status = "failed"
                error = "agent_name is required for agent_nudge jobs"
            else:
                result = await run_scheduled_agent(
                    agent_name=row.agent_name,
                    prompt_override=row.prompt_template,
                    target_channel_override=row.target_channel,
                    target_channel_id_override=row.target_channel_id,
                    notification_mode_override=row.notification_mode,
                )
                status = str(result.get("status", "completed"))
                message = str(result)
        else:
            status = "failed"
            error = f"Unsupported job_type '{row.job_type}'"
    except Exception as exc:
        status = "failed"
        error = str(exc)
        logger.exception("Persistent job %s failed", job_id)
    finally:
        finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        scheduled = scheduler.get_job(_scheduler_job_id(job_id))
        next_run = scheduled.next_run_time if scheduled else None
        once_completed_at = finished_at if row and row.schedule_type == "once" else None
        once_enabled = False if row and row.schedule_type == "once" else None
        await record_job_run(
            job_id=job_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            message=message,
            error=error,
            last_run_at=finished_at,
            next_run_at=_to_db_datetime(next_run),
            completed_at=once_completed_at,
            enabled=once_enabled,
        )


def ensure_maintenance_jobs():
    if scheduler.get_job("maintenance_prune"):
        return
    scheduler.add_job(
        run_retention_prune_job,
        "cron",
        hour=3,
        minute=17,
        id="maintenance_prune",
        replace_existing=True,
        coalesce=True,
    )
    logger.info("Configured maintenance_prune daily job")


def ensure_prayer_jobs():
    if not scheduler.get_job("prayer_daily_refresh"):
        scheduler.add_job(
            refresh_today_and_tomorrow_windows,
            "cron",
            hour=0,
            minute=5,
            id="prayer_daily_refresh",
            replace_existing=True,
            coalesce=True,
        )
        logger.info("Configured prayer_daily_refresh job")
    if not scheduler.get_job("prayer_autoclose_unknown"):
        scheduler.add_job(
            auto_mark_unknown_expired,
            "interval",
            minutes=2,
            id="prayer_autoclose_unknown",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info("Configured prayer_autoclose_unknown job")


async def run_retention_prune_job():
    memory_result = await prune_old_data(
        memory_days=settings.memory_retention_days,
        audit_days=settings.audit_retention_days,
    )
    session_result = await prune_expired_session_archives()
    logger.info("Retention prune complete: %s", {**memory_result, **session_result})


async def bootstrap_agent_jobs():
    """Register persisted jobs and keep legacy agent cadence in sync."""
    await seed_jobs_from_agent_cadence()
    await fill_missing_job_descriptions()
    for row in await list_jobs():
        try:
            await sync_persistent_job(row.id)
        except Exception as exc:
            logger.warning("Failed scheduling persistent job id=%s: %s", row.id, exc)
    ensure_maintenance_jobs()
    ensure_prayer_jobs()


async def sync_agent_job(agent_name: str, cadence: str, enabled: bool, target_channel: str | None) -> None:
    row = await upsert_agent_cadence_job(
        agent_name=agent_name,
        cadence=cadence,
        enabled=enabled,
        target_channel=target_channel,
    )
    await sync_persistent_job(row.id)


async def unschedule_agent_jobs(agent_name: str) -> None:
    await disable_agent_cadence_job(agent_name)
    rows = await list_jobs(agent_name=agent_name)
    for row in rows:
        if row.source == "agent_cadence":
            await sync_persistent_job(row.id)
