"""Persistent scheduled jobs service."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, select

from app.database import async_session
from app.models import Agent, JobRunLog, ScheduledJob, ScheduledJobCreate, ScheduledJobUpdate
from app.services.events import publish_event

DEFAULT_JOB_TIMEZONE = "Africa/Casablanca"
DEFAULT_NOTIFICATION_MODE = "channel"
DEFAULT_SCHEDULE_TYPE = "cron"


def default_job_description(
    *,
    name: str,
    agent_name: str | None,
    schedule_type: str,
    cron_expression: str | None,
    run_at: datetime | None,
    timezone: str,
    notification_mode: str,
    target_channel: str | None,
    target_channel_id: str | None,
) -> str:
    if schedule_type == "once":
        if run_at is not None:
            local_run = _to_aware_utc(run_at).astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")
            schedule_summary = f"runs once at '{local_run}'"
        else:
            schedule_summary = "runs once at an unspecified time"
    else:
        schedule_summary = f"runs on cron '{cron_expression}'"

    if notification_mode == "silent":
        target = "without posting to Discord"
    elif target_channel:
        target = f"and posts to #{target_channel}"
    elif target_channel_id:
        target = f"and posts to <#{target_channel_id}>"
    else:
        target = "and posts to its mapped channel"
    owner = agent_name or "system"
    return (
        f"{name}: runs for agent '{owner}', {schedule_summary}, in timezone "
        f"'{timezone}' {target}."
    )


def normalize_cron_expression(cron_expression: str | None) -> str:
    parts = (cron_expression or "").split()
    if len(parts) == 3:
        minute, hour, day_of_week = parts
        return f"{minute} {hour} * * {day_of_week}"
    if len(parts) == 5:
        return str(cron_expression)
    raise ValueError("Cron must have either 3 fields (minute hour day_of_week) or 5 fields")


def validate_timezone(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"Invalid timezone '{timezone_name}'") from exc
    return timezone_name


def validate_notification_mode(notification_mode: str | None) -> str:
    value = str(notification_mode or DEFAULT_NOTIFICATION_MODE).strip().lower()
    if value not in {"channel", "silent"}:
        raise ValueError("notification_mode must be either 'channel' or 'silent'")
    return value


def normalize_follow_up_after_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, min(minutes, 10080))


def infer_schedule_type(
    schedule_type: str | None,
    *,
    cron_expression: str | None,
    run_at: datetime | None,
) -> str:
    value = str(schedule_type or "").strip().lower()
    if not value:
        return "once" if run_at is not None and not (cron_expression or "").strip() else DEFAULT_SCHEDULE_TYPE
    if value not in {"cron", "once"}:
        raise ValueError("schedule_type must be either 'cron' or 'once'")
    return value


def _to_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_run_at(run_at: datetime | None, timezone_name: str, *, assume_utc: bool = False) -> datetime | None:
    if run_at is None:
        return None
    if run_at.tzinfo is None:
        aware = run_at.replace(tzinfo=timezone.utc if assume_utc else ZoneInfo(timezone_name))
    else:
        aware = run_at
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def compute_next_run(cron_expression: str, timezone_name: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    trigger = CronTrigger.from_crontab(normalize_cron_expression(cron_expression), timezone=ZoneInfo(timezone_name))
    return trigger.get_next_fire_time(previous_fire_time=None, now=now)


def prepare_job_payload(payload: dict, *, existing: ScheduledJob | None = None) -> dict:
    normalized = dict(payload)
    timezone_name = validate_timezone(normalized.get("timezone") or getattr(existing, "timezone", None) or DEFAULT_JOB_TIMEZONE)
    source_name = str(normalized.get("source") or getattr(existing, "source", "") or "").strip().lower()
    cron_expression = normalized.get("cron_expression", getattr(existing, "cron_expression", None))
    run_at = normalized.get("run_at", getattr(existing, "run_at", None))
    schedule_type = infer_schedule_type(
        normalized.get("schedule_type", getattr(existing, "schedule_type", None)),
        cron_expression=cron_expression,
        run_at=run_at,
    )
    notification_mode = validate_notification_mode(
        normalized.get("notification_mode", getattr(existing, "notification_mode", None))
    )
    if source_name == "commitment_follow_up":
        normalized.setdefault("expect_reply", True)
        normalized.setdefault("follow_up_after_minutes", 120)

    normalized["timezone"] = timezone_name
    normalized["schedule_type"] = schedule_type
    normalized["notification_mode"] = notification_mode
    normalized["expect_reply"] = bool(normalized.get("expect_reply", getattr(existing, "expect_reply", False)))
    normalized["follow_up_after_minutes"] = normalize_follow_up_after_minutes(
        normalized.get("follow_up_after_minutes", getattr(existing, "follow_up_after_minutes", None))
    )
    if notification_mode == "silent":
        normalized["target_channel"] = None
        normalized["target_channel_id"] = None

    if schedule_type == "cron":
        normalized["cron_expression"] = normalize_cron_expression(cron_expression)
        normalized["run_at"] = None
        if "completed_at" not in normalized and existing and existing.schedule_type != "cron":
            normalized["completed_at"] = None
    else:
        normalized["cron_expression"] = None
        normalized["run_at"] = normalize_run_at(
            run_at,
            timezone_name,
            assume_utc=source_name in {"discord_nl", "discord"},
        )
        if normalized["run_at"] is None:
            raise ValueError("run_at is required for one-time jobs")
        if (
            "completed_at" not in normalized
            and (
                "run_at" in payload
                or normalized.get("enabled") is True
                or (existing is not None and existing.schedule_type != "once")
            )
        ):
            normalized["completed_at"] = None
    return normalized


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
    payload = prepare_job_payload(data.model_dump())
    if not payload.get("description"):
        payload["description"] = default_job_description(
            name=payload["name"],
            agent_name=payload.get("agent_name"),
            schedule_type=payload["schedule_type"],
            cron_expression=payload["cron_expression"],
            run_at=payload.get("run_at"),
            timezone=payload["timezone"],
            notification_mode=payload["notification_mode"],
            target_channel=payload.get("target_channel"),
            target_channel_id=payload.get("target_channel_id"),
        )
    async with async_session() as db:
        row = ScheduledJob(**payload)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        await publish_event(
            "jobs.updated",
            {"kind": "job", "id": str(row.id)},
            {"action": "created", "job_id": row.id, "name": row.name, "status": row.last_status},
        )
        return row


async def update_job(job_id: int, data: ScheduledJobUpdate) -> ScheduledJob | None:
    async with async_session() as db:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        row = result.scalar_one_or_none()
        if not row:
            return None

        payload = data.model_dump(exclude_unset=True)
        payload = prepare_job_payload(payload, existing=row)

        for key, value in payload.items():
            setattr(row, key, value)
        if "description" not in payload or not (row.description or "").strip():
            row.description = default_job_description(
                name=row.name,
                agent_name=row.agent_name,
                schedule_type=row.schedule_type,
                cron_expression=row.cron_expression,
                run_at=row.run_at,
                timezone=row.timezone,
                notification_mode=row.notification_mode,
                target_channel=row.target_channel,
                target_channel_id=row.target_channel_id,
            )
        await db.commit()
        await db.refresh(row)
        await publish_event(
            "jobs.updated",
            {"kind": "job", "id": str(row.id)},
            {
                "action": "updated",
                "job_id": row.id,
                "paused": row.paused,
                "enabled": row.enabled,
                "last_status": row.last_status,
            },
        )
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
        await publish_event(
            "jobs.updated",
            {"kind": "job", "id": str(job_id)},
            {"action": "deleted", "job_id": job_id},
        )
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
    completed_at: datetime | None = None,
    enabled: bool | None = None,
    notification_channel: str | None = None,
    notification_channel_id: str | None = None,
    notification_message_id: str | None = None,
    awaiting_reply_until: datetime | None = None,
) -> None:
    async with async_session() as db:
        log_row = JobRunLog(
            job_id=job_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            message=message,
            error=error,
            notification_channel=notification_channel,
            notification_channel_id=notification_channel_id,
            notification_message_id=notification_message_id,
            awaiting_reply_until=awaiting_reply_until,
        )
        db.add(log_row)
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        row = result.scalar_one_or_none()
        if row:
            row.last_status = status
            row.last_error = error
            row.last_run_at = last_run_at
            row.next_run_at = next_run_at
            if completed_at is not None:
                row.completed_at = completed_at
            if enabled is not None:
                row.enabled = enabled
                if not enabled:
                    row.paused = False
        await db.commit()
        await publish_event(
            "jobs.run.updated",
            {"kind": "job_run", "id": str(log_row.id)},
            {
                "job_id": job_id,
                "run_id": log_row.id,
                "status": status,
                "error": error,
                "finished_at": finished_at.isoformat(),
            },
        )
        if message:
            await publish_event(
                "jobs.run.log.appended",
                {"kind": "job_run", "id": str(log_row.id)},
                {"job_id": job_id, "run_id": log_row.id, "lines": [message]},
            )


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
                existing.schedule_type = "cron"
                existing.cron_expression = normalized
                existing.run_at = None
                existing.timezone = "Africa/Casablanca"
                existing.notification_mode = "channel"
                existing.enabled = bool(agent.enabled)
                existing.paused = not bool(agent.enabled)
                existing.target_channel = agent.discord_channel
                existing.target_channel_id = None
                existing.completed_at = None
                existing.description = default_job_description(
                    name=existing.name,
                    agent_name=existing.agent_name,
                    schedule_type=existing.schedule_type,
                    cron_expression=existing.cron_expression,
                    run_at=existing.run_at,
                    timezone=existing.timezone,
                    notification_mode=existing.notification_mode,
                    target_channel=existing.target_channel,
                    target_channel_id=existing.target_channel_id,
                )
                continue

            db.add(
                ScheduledJob(
                    name=job_name,
                    description=default_job_description(
                        name=job_name,
                        agent_name=agent.name,
                        schedule_type="cron",
                        cron_expression=normalized,
                        run_at=None,
                        timezone="Africa/Casablanca",
                        notification_mode="channel",
                        target_channel=agent.discord_channel,
                        target_channel_id=None,
                    ),
                    agent_name=agent.name,
                    job_type="agent_nudge",
                    schedule_type="cron",
                    cron_expression=normalized,
                    run_at=None,
                    timezone="Africa/Casablanca",
                    notification_mode="channel",
                    target_channel=agent.discord_channel,
                    target_channel_id=None,
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
                description=default_job_description(
                    name=f"{agent_name} cadence",
                    agent_name=agent_name,
                    schedule_type="cron",
                    cron_expression=normalized,
                    run_at=None,
                    timezone="Africa/Casablanca",
                    notification_mode="channel",
                    target_channel=target_channel,
                    target_channel_id=None,
                ),
                agent_name=agent_name,
                job_type="agent_nudge",
                schedule_type="cron",
                cron_expression=normalized,
                run_at=None,
                timezone="Africa/Casablanca",
                notification_mode="channel",
                target_channel=target_channel,
                target_channel_id=None,
                enabled=enabled,
                paused=not enabled,
                approval_required=True,
                source="agent_cadence",
                created_by="agent_router",
            )
            db.add(row)
        else:
            row.schedule_type = "cron"
            row.cron_expression = normalized
            row.run_at = None
            row.target_channel = target_channel
            row.target_channel_id = None
            row.notification_mode = "channel"
            row.enabled = enabled
            row.paused = not enabled
            row.timezone = row.timezone or "Africa/Casablanca"
            row.completed_at = None
            row.description = row.description or default_job_description(
                name=row.name,
                agent_name=row.agent_name,
                schedule_type=row.schedule_type,
                cron_expression=row.cron_expression,
                run_at=row.run_at,
                timezone=row.timezone,
                notification_mode=row.notification_mode,
                target_channel=row.target_channel,
                target_channel_id=row.target_channel_id,
            )
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


async def fill_missing_job_descriptions() -> int:
    updated = 0
    async with async_session() as db:
        result = await db.execute(select(ScheduledJob))
        rows = list(result.scalars().all())
        for row in rows:
            if (row.description or "").strip():
                continue
            row.description = default_job_description(
                name=row.name,
                agent_name=row.agent_name,
                schedule_type=row.schedule_type or "cron",
                cron_expression=row.cron_expression,
                run_at=row.run_at,
                timezone=row.timezone,
                notification_mode=row.notification_mode or "channel",
                target_channel=row.target_channel,
                target_channel_id=row.target_channel_id,
            )
            updated += 1
        if updated:
            await db.commit()
    return updated
