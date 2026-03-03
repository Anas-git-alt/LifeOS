"""Persistent scheduled jobs service."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, select

from app.database import async_session
from app.models import Agent, JobRunLog, ScheduledJob, ScheduledJobCreate, ScheduledJobUpdate


def normalize_cron_expression(cron_expression: str) -> str:
    parts = (cron_expression or "").split()
    if len(parts) == 3:
        minute, hour, day_of_week = parts
        return f"{minute} {hour} * * {day_of_week}"
    if len(parts) == 5:
        return cron_expression
    raise ValueError("Cron must have either 3 fields (minute hour day_of_week) or 5 fields")


def validate_timezone(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"Invalid timezone '{timezone_name}'") from exc
    return timezone_name


def compute_next_run(cron_expression: str, timezone_name: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    trigger = CronTrigger.from_crontab(normalize_cron_expression(cron_expression), timezone=ZoneInfo(timezone_name))
    return trigger.get_next_fire_time(previous_fire_time=None, now=now)


async def list_jobs(agent_name: str | None = None) -> list[ScheduledJob]:
    async with async_session() as db:
        query = select(ScheduledJob).order_by(ScheduledJob.id.asc())
        if agent_name:
            query = query.where(ScheduledJob.agent_name == agent_name)
        result = await db.execute(query)
        return list(result.scalars().all())


async def get_job(job_id: int) -> ScheduledJob | None:
    async with async_session() as db:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        return result.scalar_one_or_none()


async def create_job(data: ScheduledJobCreate) -> ScheduledJob:
    payload = data.model_dump()
    payload["cron_expression"] = normalize_cron_expression(payload["cron_expression"])
    payload["timezone"] = validate_timezone(payload["timezone"])
    async with async_session() as db:
        row = ScheduledJob(**payload)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def update_job(job_id: int, data: ScheduledJobUpdate) -> ScheduledJob | None:
    async with async_session() as db:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        row = result.scalar_one_or_none()
        if not row:
            return None

        payload = data.model_dump(exclude_unset=True)
        if "cron_expression" in payload and payload["cron_expression"]:
            payload["cron_expression"] = normalize_cron_expression(payload["cron_expression"])
        if "timezone" in payload and payload["timezone"]:
            payload["timezone"] = validate_timezone(payload["timezone"])

        for key, value in payload.items():
            setattr(row, key, value)
        await db.commit()
        await db.refresh(row)
        return row


async def delete_job(job_id: int) -> bool:
    async with async_session() as db:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        row = result.scalar_one_or_none()
        if not row:
            return False
        await db.execute(delete(JobRunLog).where(JobRunLog.job_id == job_id))
        await db.delete(row)
        await db.commit()
        return True


async def pause_job(job_id: int) -> ScheduledJob | None:
    return await update_job(job_id, ScheduledJobUpdate(paused=True))


async def resume_job(job_id: int) -> ScheduledJob | None:
    return await update_job(job_id, ScheduledJobUpdate(paused=False, enabled=True))


async def list_job_run_logs(job_id: int, limit: int = 20) -> list[JobRunLog]:
    async with async_session() as db:
        result = await db.execute(
            select(JobRunLog)
            .where(JobRunLog.job_id == job_id)
            .order_by(JobRunLog.created_at.desc(), JobRunLog.id.desc())
            .limit(max(1, min(limit, 200)))
        )
        return list(result.scalars().all())


async def record_job_run(
    *,
    job_id: int,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    message: str | None,
    error: str | None,
    last_run_at: datetime | None,
    next_run_at: datetime | None,
) -> None:
    async with async_session() as db:
        log_row = JobRunLog(
            job_id=job_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            message=message,
            error=error,
        )
        db.add(log_row)
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        row = result.scalar_one_or_none()
        if row:
            row.last_status = status
            row.last_error = error
            row.last_run_at = last_run_at
            row.next_run_at = next_run_at
        await db.commit()


async def seed_jobs_from_agent_cadence() -> int:
    """Ensure each enabled agent with cadence has a persisted job row."""
    created = 0
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.enabled.is_(True)).where(Agent.cadence.is_not(None)))
        agents = [agent for agent in result.scalars().all() if (agent.cadence or "").strip()]

        for agent in agents:
            job_name = f"{agent.name} cadence"
            existing_result = await db.execute(
                select(ScheduledJob)
                .where(ScheduledJob.agent_name == agent.name)
                .where(ScheduledJob.source == "agent_cadence")
                .limit(1)
            )
            existing = existing_result.scalar_one_or_none()
            normalized = normalize_cron_expression(agent.cadence or "")
            if existing:
                existing.cron_expression = normalized
                existing.timezone = "Africa/Casablanca"
                existing.enabled = bool(agent.enabled)
                existing.paused = not bool(agent.enabled)
                existing.target_channel = agent.discord_channel
                continue

            db.add(
                ScheduledJob(
                    name=job_name,
                    agent_name=agent.name,
                    job_type="agent_nudge",
                    cron_expression=normalized,
                    timezone="Africa/Casablanca",
                    target_channel=agent.discord_channel,
                    enabled=True,
                    paused=False,
                    approval_required=True,
                    source="agent_cadence",
                    created_by="system_seed",
                )
            )
            created += 1
        await db.commit()
    return created


async def upsert_agent_cadence_job(
    *,
    agent_name: str,
    cadence: str,
    enabled: bool,
    target_channel: str | None,
) -> ScheduledJob:
    normalized = normalize_cron_expression(cadence)
    async with async_session() as db:
        existing_result = await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.agent_name == agent_name)
            .where(ScheduledJob.source == "agent_cadence")
            .limit(1)
        )
        row = existing_result.scalar_one_or_none()
        if not row:
            row = ScheduledJob(
                name=f"{agent_name} cadence",
                agent_name=agent_name,
                job_type="agent_nudge",
                cron_expression=normalized,
                timezone="Africa/Casablanca",
                target_channel=target_channel,
                enabled=enabled,
                paused=not enabled,
                approval_required=True,
                source="agent_cadence",
                created_by="agent_router",
            )
            db.add(row)
        else:
            row.cron_expression = normalized
            row.target_channel = target_channel
            row.enabled = enabled
            row.paused = not enabled
            row.timezone = row.timezone or "Africa/Casablanca"
        await db.commit()
        await db.refresh(row)
        return row


async def disable_agent_cadence_job(agent_name: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.agent_name == agent_name)
            .where(ScheduledJob.source == "agent_cadence")
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        row.enabled = False
        row.paused = True
        await db.commit()
