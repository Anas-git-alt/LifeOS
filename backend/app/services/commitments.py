"""Commitment capture follow-up job helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import async_session
from app.models import AuditLog, LifeItem, ScheduledJob, ScheduledJobCreate, ScheduledJobUpdate, UserProfile
from app.services.jobs import create_job, get_job, update_job
from app.services.scheduler import sync_persistent_job

DEFAULT_TIMEZONE = "Africa/Casablanca"
DEFAULT_FOLLOW_UP_HOUR = 9


def _resolve_tz_name(value: str | None) -> str:
    candidate = str(value or "").strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(candidate)
        return candidate
    except Exception:
        return DEFAULT_TIMEZONE


def _to_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_naive_utc(value: datetime | None) -> datetime | None:
    aware = _to_aware_utc(value)
    return aware.replace(tzinfo=None) if aware else None


def compute_follow_up_run_at(
    *,
    due_at: datetime | None,
    timezone_name: str,
    now_utc: datetime | None = None,
) -> datetime:
    now_utc = _to_aware_utc(now_utc) or datetime.now(timezone.utc)
    if due_at is not None:
        due_utc = _to_aware_utc(due_at) or now_utc
        candidate = due_utc - timedelta(hours=2)
        minimum = now_utc + timedelta(minutes=30)
        return max(candidate, minimum).replace(tzinfo=None)

    tz = ZoneInfo(_resolve_tz_name(timezone_name))
    next_local = now_utc.astimezone(tz).replace(
        hour=DEFAULT_FOLLOW_UP_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(days=1)
    return next_local.astimezone(timezone.utc).replace(tzinfo=None)


def resolve_job_follow_up_due_at(job: ScheduledJob | None) -> datetime | None:
    if not job or not job.enabled or job.paused or job.completed_at:
        return None
    return job.next_run_at or job.run_at


def build_follow_up_prompt(item: LifeItem, *, timezone_name: str, run_at: datetime) -> str:
    due_text = "no explicit deadline"
    if item.due_at:
        due_text = (_to_aware_utc(item.due_at) or datetime.now(timezone.utc)).astimezone(
            ZoneInfo(_resolve_tz_name(timezone_name))
        ).strftime("%Y-%m-%d %H:%M")
    reminder_local = (_to_aware_utc(run_at) or datetime.now(timezone.utc)).astimezone(
        ZoneInfo(_resolve_tz_name(timezone_name))
    ).strftime("%Y-%m-%d %H:%M")
    notes = (item.notes or "").strip()
    return (
        "MODE: reminder_nudge\n"
        f"Commitment id: {item.id}\n"
        f"Title: {item.title}\n"
        f"Priority: {item.priority}\n"
        f"Due: {due_text}\n"
        f"Reminder local time: {reminder_local}\n"
        f"Notes: {notes[:800] if notes else 'none'}\n"
        "Write a short supportive follow-up that reminds the user what they said they would do, "
        "why it matters, and one visible next step. Keep it concrete."
    )


async def _load_profile_timezone() -> str:
    async with async_session() as db:
        result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = result.scalar_one_or_none()
        return _resolve_tz_name(profile.timezone if profile else DEFAULT_TIMEZONE)


async def upsert_follow_up_job(
    item_id: int,
    *,
    timezone_name: str | None = None,
    target_channel: str | None = None,
    target_channel_id: str | None = None,
) -> ScheduledJob | None:
    async with async_session() as db:
        result = await db.execute(select(LifeItem).where(LifeItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return None

        effective_timezone = _resolve_tz_name(timezone_name)
        run_at = compute_follow_up_run_at(
            due_at=item.due_at,
            timezone_name=effective_timezone,
            now_utc=datetime.now(timezone.utc),
        )
        prompt_template = build_follow_up_prompt(
            item,
            timezone_name=effective_timezone,
            run_at=run_at.replace(tzinfo=timezone.utc),
        )
        notification_mode = "channel" if (target_channel or target_channel_id) else "silent"
        job_name = f"Commitment follow-up #{item.id}"
        job_description = f"Follow-up reminder for commitment #{item.id}: {item.title}"

        existing_job = None
        if item.follow_up_job_id:
            existing_job = await get_job(item.follow_up_job_id)

        if existing_job:
            next_notification_mode = notification_mode
            next_target_channel = target_channel
            next_target_channel_id = target_channel_id
            if not target_channel and not target_channel_id:
                next_notification_mode = existing_job.notification_mode
                next_target_channel = existing_job.target_channel
                next_target_channel_id = existing_job.target_channel_id
            payload = ScheduledJobUpdate(
                name=job_name,
                description=job_description,
                agent_name="commitment-coach",
                schedule_type="once",
                run_at=run_at,
                timezone=effective_timezone,
                notification_mode=next_notification_mode,
                target_channel=next_target_channel if next_notification_mode == "channel" else None,
                target_channel_id=next_target_channel_id if next_notification_mode == "channel" else None,
                prompt_template=prompt_template,
                enabled=True,
                paused=False,
                approval_required=False,
                source="commitment_follow_up",
                created_by="lifeos",
                config_json={
                    "origin": "commitment_capture",
                    "life_item_id": item.id,
                },
            )
            await update_job(existing_job.id, payload)
            job_id = existing_job.id
            action = "life_item_follow_up_rescheduled"
        else:
            created = await create_job(
                ScheduledJobCreate(
                    name=job_name,
                    description=job_description,
                    agent_name="commitment-coach",
                    schedule_type="once",
                    run_at=run_at,
                    timezone=effective_timezone,
                    notification_mode=notification_mode,
                    target_channel=target_channel if notification_mode == "channel" else None,
                    target_channel_id=target_channel_id if notification_mode == "channel" else None,
                    prompt_template=prompt_template,
                    enabled=True,
                    paused=False,
                    approval_required=False,
                    source="commitment_follow_up",
                    created_by="lifeos",
                    config_json={
                        "origin": "commitment_capture",
                        "life_item_id": item.id,
                    },
                )
            )
            job_id = created.id
            item.follow_up_job_id = created.id
            action = "life_item_follow_up_scheduled"

        db.add(
            AuditLog(
                agent_name="commitment-loop",
                action=action,
                details=f"item_id={item.id} job_id={job_id} run_at={run_at.isoformat()}",
                status="completed",
            )
        )
        await db.commit()

    await sync_persistent_job(job_id)
    refreshed = await get_job(job_id)
    if refreshed is None:
        return None
    return refreshed


async def disable_follow_up_job(item_id: int, *, reason: str) -> ScheduledJob | None:
    async with async_session() as db:
        result = await db.execute(select(LifeItem).where(LifeItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item or not item.follow_up_job_id:
            return None

        job_id = item.follow_up_job_id
        db.add(
            AuditLog(
                agent_name="commitment-loop",
                action="life_item_follow_up_disabled",
                details=f"item_id={item.id} job_id={job_id} reason={reason}",
                status="completed",
            )
        )
        await db.commit()

    await update_job(job_id, ScheduledJobUpdate(enabled=False, paused=False))
    await sync_persistent_job(job_id)
    return await get_job(job_id)


async def get_commitment_timezone(preferred: str | None = None) -> str:
    if preferred:
        return _resolve_tz_name(preferred)
    return await _load_profile_timezone()
