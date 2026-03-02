"""Scheduler service for periodic agent runs and maintenance tasks."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Agent
from app.services.memory import prune_old_data
from app.services.orchestrator import run_scheduled_agent
from app.services.prayer_service import auto_mark_unknown_expired, refresh_today_and_tomorrow_windows

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.timezone)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
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
    return minute, hour, day_of_week


def add_agent_job(agent_name: str, cron_expression: str):
    minute, hour, day_of_week = _parse_cadence(cron_expression)
    job_id = f"agent_{agent_name}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        run_scheduled_agent,
        "cron",
        minute=minute,
        hour=hour,
        day_of_week=day_of_week,
        id=job_id,
        kwargs={"agent_name": agent_name},
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    logger.info("Scheduled %s at minute=%s hour=%s dow=%s", agent_name, minute, hour, day_of_week)


def remove_agent_job(agent_name: str):
    job_id = f"agent_{agent_name}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Removed scheduled job %s", job_id)


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
    result = await prune_old_data(
        memory_days=settings.memory_retention_days,
        audit_days=settings.audit_retention_days,
    )
    logger.info("Retention prune complete: %s", result)


async def bootstrap_agent_jobs():
    """Register all enabled agent cadence jobs from DB."""
    async with async_session() as db:
        result = await db.execute(
            select(Agent).where(Agent.enabled.is_(True)).where(Agent.cadence.is_not(None))
        )
        agents = [agent for agent in result.scalars().all() if (agent.cadence or "").strip()]
    for agent in agents:
        try:
            add_agent_job(agent.name, agent.cadence or "")
        except Exception as exc:
            logger.warning("Failed scheduling agent '%s': %s", agent.name, exc)
    ensure_maintenance_jobs()
    ensure_prayer_jobs()
