"""Context event journal and review-first wiki curation."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import (
    ContextEvent,
    IntakeEntry,
    JobRunLog,
    LifeCheckinCreate,
    ScheduledJob,
    SharedMemoryPromoteRequest,
    SharedMemoryProposal,
)
from app.services.events import publish_event
from app.services.discord_notify import send_channel_message
from app.services.shared_memory import create_shared_memory_review_proposal, list_shared_memory_proposals

VALID_DOMAINS = {"deen", "family", "work", "health", "planning"}
_DONE_RE = re.compile(r"\b(done|finished|complete(?:d)?|sent|submitted|handled|closed)\b", re.IGNORECASE)
_MISSED_RE = re.compile(r"\b(missed|skip(?:ped)?|failed|cancel(?:ed|led)?|not doing|did not)\b", re.IGNORECASE)
_ACTION_RE = re.compile(r"\b(action|todo|next|follow[- ]?up|owner|deadline|due)\b", re.IGNORECASE)


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat()


def _infer_domain(text: str, fallback: str | None = None) -> str:
    candidate = _clean(fallback).lower()
    if candidate in VALID_DOMAINS:
        return candidate
    lowered = text.lower()
    if any(token in lowered for token in ["prayer", "quran", "deen", "salah", "adhkar"]):
        return "deen"
    if any(token in lowered for token in ["sleep", "workout", "gym", "health", "meal", "fitness"]):
        return "health"
    if any(token in lowered for token in ["wife", "family", "home", "kids"]):
        return "family"
    if any(token in lowered for token in ["client", "work", "repo", "deploy", "meeting", "project", "invoice"]):
        return "work"
    return "planning"


def _title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip(" #-*\t")
        if len(cleaned) >= 4:
            return cleaned[:120]
    return fallback


def _proposal_title(event: ContextEvent) -> str:
    if event.title:
        return event.title[:180]
    prefix = "Meeting" if event.event_type == "meeting_summary" else "Job Reply"
    return f"{prefix}: {_title_from_text(event.raw_text, 'Context Update')}"[:180]


def _proposal_content(event: ContextEvent) -> str:
    metadata = event.metadata_json or {}
    source_bits = [
        f"- Event id: {event.id}",
        f"- Event type: {event.event_type}",
        f"- Source: {event.source}",
    ]
    if event.job_id:
        source_bits.append(f"- Job id: {event.job_id}")
    if event.job_run_id:
        source_bits.append(f"- Job run id: {event.job_run_id}")
    if event.discord_reply_message_id:
        source_bits.append(f"- Discord reply: {event.discord_reply_message_id}")
    if metadata.get("meeting_tags"):
        source_bits.append(f"- Tags: {', '.join(metadata['meeting_tags'])}")

    return (
        "## Source\n"
        + "\n".join(source_bits)
        + "\n\n## Summary\n"
        + (_clean(event.summary) or _clean(event.raw_text))
        + "\n\n## Raw Intake\n"
        + _clean(event.raw_text)
        + "\n"
    )


def _extract_action_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        cleaned = line.strip(" -*\t")
        if len(cleaned) < 6:
            continue
        if _ACTION_RE.search(cleaned):
            lines.append(cleaned[:300])
    return lines[:5]


async def _create_intake_entries_for_actions(event: ContextEvent) -> list[int]:
    action_lines = _extract_action_lines(event.raw_text)
    if not action_lines:
        return []
    created: list[int] = []
    async with async_session() as db:
        for line in action_lines:
            entry = IntakeEntry(
                source="context_event",
                source_agent=event.source_agent or "wiki-curator",
                source_session_id=event.source_session_id,
                raw_text=line,
                title=line[:300],
                summary=f"Action extracted from context event #{event.id}",
                domain=event.domain,
                kind="task",
                status="ready",
                desired_outcome=line,
                next_action=line,
                follow_up_questions_json=[],
                promotion_payload_json={
                    "title": line[:300],
                    "kind": "task",
                    "domain": event.domain,
                    "priority": "medium",
                },
                structured_data_json={"context_event_id": event.id},
            )
            db.add(entry)
            await db.flush()
            created.append(entry.id)
        await db.commit()
    return created


async def list_context_events(
    *,
    event_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[ContextEvent]:
    async with async_session() as db:
        query = select(ContextEvent).order_by(ContextEvent.created_at.desc(), ContextEvent.id.desc())
        if event_type:
            query = query.where(ContextEvent.event_type == event_type)
        if status:
            query = query.where(ContextEvent.status == status)
        query = query.limit(max(1, min(limit, 200)))
        result = await db.execute(query)
        return list(result.scalars().all())


async def get_context_event(event_id: int) -> ContextEvent | None:
    async with async_session() as db:
        return await db.get(ContextEvent, event_id)


async def _existing_proposals(event: ContextEvent) -> list[SharedMemoryProposal]:
    proposal_ids = ((event.metadata_json or {}).get("proposal_ids") or [])
    if not proposal_ids:
        return []
    pending = await list_shared_memory_proposals(status="")
    by_id = {row.id: row for row in pending}
    return [by_id[item] for item in proposal_ids if item in by_id]


async def curate_context_event(event_id: int) -> tuple[ContextEvent, list[SharedMemoryProposal], list[int]]:
    event = await get_context_event(event_id)
    if not event:
        raise ValueError(f"Context event #{event_id} not found")

    if event.status == "curated":
        return event, await _existing_proposals(event), list((event.metadata_json or {}).get("intake_entry_ids") or [])

    proposal = await create_shared_memory_review_proposal(
        SharedMemoryPromoteRequest(
            agent_name=event.source_agent or "wiki-curator",
            title=_proposal_title(event),
            content=_proposal_content(event),
            scope="shared_domain",
            domain=event.domain,
            session_id=event.source_session_id,
            source_uri=f"lifeos://context-events/{event.id}",
            tags=["lifeos", "context-event", event.event_type],
            confidence="medium",
        )
    )
    intake_entry_ids = await _create_intake_entries_for_actions(event)

    async with async_session() as db:
        row = await db.get(ContextEvent, event.id)
        if not row:
            raise ValueError(f"Context event #{event_id} not found")
        metadata = dict(row.metadata_json or {})
        metadata["proposal_ids"] = [proposal.id]
        metadata["intake_entry_ids"] = intake_entry_ids
        row.metadata_json = metadata
        row.status = "curated"
        row.curated_at = _now_naive_utc()
        await db.commit()
        await db.refresh(row)
        event = row

    return event, [proposal], intake_entry_ids


async def capture_meeting_summary(payload) -> tuple[ContextEvent, list[SharedMemoryProposal], list[int]]:
    summary = _clean(payload.summary)
    if not summary:
        raise ValueError("summary is required")
    domain = _infer_domain(summary, payload.domain)
    async with async_session() as db:
        event = ContextEvent(
            event_type="meeting_summary",
            source=payload.source or "api",
            source_agent=payload.source_agent or "wiki-curator",
            source_session_id=payload.session_id,
            title=_clean(payload.title) or _title_from_text(summary, "Meeting Summary"),
            summary=summary[:2000],
            raw_text=summary,
            domain=domain,
            metadata_json={"meeting_tags": payload.tags or []},
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
    return await curate_context_event(event.id)


def classify_job_reply_result(text: str) -> str:
    if _MISSED_RE.search(text or ""):
        return "missed"
    if _DONE_RE.search(text or ""):
        return "done"
    return "partial"


async def capture_job_reply(payload) -> tuple[ContextEvent, JobRunLog, int | None, str | None, list[SharedMemoryProposal]]:
    reply_text = _clean(payload.reply_text)
    if not reply_text:
        raise ValueError("reply_text is required")
    notification_message_id = _clean(payload.notification_message_id)
    if not notification_message_id:
        raise ValueError("notification_message_id is required")

    async with async_session() as db:
        query = (
            select(JobRunLog, ScheduledJob)
            .join(ScheduledJob, ScheduledJob.id == JobRunLog.job_id)
            .where(JobRunLog.notification_message_id == notification_message_id)
            .order_by(JobRunLog.created_at.desc(), JobRunLog.id.desc())
            .limit(1)
        )
        if payload.discord_channel_id:
            query = query.where(JobRunLog.notification_channel_id == str(payload.discord_channel_id))
        result = await db.execute(query)
        row = result.first()
        if not row:
            raise ValueError("No job notification found for that Discord message")
        run, job = row
        run.reply_count = int(run.reply_count or 0) + 1
        metadata = dict(job.config_json or {})
        life_item_id = metadata.get("life_item_id")
        event = ContextEvent(
            event_type="job_reply",
            source=payload.source or "discord_reply",
            source_agent=job.agent_name,
            job_id=job.id,
            job_run_id=run.id,
            life_item_id=int(life_item_id) if str(life_item_id or "").isdigit() else None,
            discord_channel_id=payload.discord_channel_id or run.notification_channel_id,
            discord_message_id=run.notification_message_id,
            discord_reply_message_id=payload.discord_reply_message_id,
            discord_user_id=payload.discord_user_id,
            title=f"Reply to {job.name}",
            summary=reply_text[:2000],
            raw_text=reply_text,
            domain=_infer_domain(f"{job.name} {job.description or ''} {reply_text}"),
            metadata_json={"job_name": job.name},
        )
        db.add(event)
        await db.commit()
        await db.refresh(run)
        await db.refresh(event)

    await publish_event(
        "jobs.run.updated",
        {"kind": "job_run", "id": str(run.id)},
        {
            "job_id": run.job_id,
            "run_id": run.id,
            "status": run.status,
            "reply_count": run.reply_count,
            "awaiting_reply_until": _iso(run.awaiting_reply_until),
            "no_reply_follow_up_sent_at": _iso(run.no_reply_follow_up_sent_at),
        },
    )

    life_checkin_id: int | None = None
    life_checkin_result: str | None = None
    if event.life_item_id:
        from app.services.life import add_checkin

        life_checkin_result = classify_job_reply_result(reply_text)
        checkin, _item = await add_checkin(
            event.life_item_id,
            LifeCheckinCreate(result=life_checkin_result, note=f"Discord reply: {reply_text}"),
        )
        life_checkin_id = checkin.id if checkin else None

    event, proposals, _intake_ids = await curate_context_event(event.id)
    return event, run, life_checkin_id, life_checkin_result, proposals


async def run_no_reply_followups(now: datetime | None = None) -> dict[str, int]:
    now_utc = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    async with async_session() as db:
        result = await db.execute(
            select(JobRunLog, ScheduledJob)
            .join(ScheduledJob, ScheduledJob.id == JobRunLog.job_id)
            .where(
                ScheduledJob.expect_reply.is_(True),
                JobRunLog.notification_message_id.is_not(None),
                JobRunLog.reply_count == 0,
                JobRunLog.awaiting_reply_until.is_not(None),
                JobRunLog.awaiting_reply_until <= now_utc,
                JobRunLog.no_reply_follow_up_sent_at.is_(None),
            )
            .order_by(JobRunLog.awaiting_reply_until.asc())
            .limit(20)
        )
        rows = list(result.all())

    sent = 0
    for run, job in rows:
        content = (
            f"Following up on job #{job.id} ({job.name}). "
            "Reply to the original notification when you can, even with a quick status."
        )
        delivered = await send_channel_message(run.notification_channel, content, channel_id=run.notification_channel_id)
        async with async_session() as db:
            current_run = await db.get(JobRunLog, run.id)
            if not current_run or current_run.no_reply_follow_up_sent_at is not None:
                continue
            current_run.no_reply_follow_up_sent_at = now_utc
            event = ContextEvent(
                event_type="job_no_reply_followup",
                source="scheduler",
                source_agent=job.agent_name,
                job_id=job.id,
                job_run_id=run.id,
                discord_channel_id=run.notification_channel_id,
                discord_message_id=run.notification_message_id,
                title=f"No reply follow-up for {job.name}",
                summary=content,
                raw_text=content,
                domain=_infer_domain(f"{job.name} {job.description or ''}"),
                status="logged",
                metadata_json={"delivered": delivered},
            )
            db.add(event)
            await db.commit()
            await publish_event(
                "jobs.run.updated",
                {"kind": "job_run", "id": str(current_run.id)},
                {
                    "job_id": current_run.job_id,
                    "run_id": current_run.id,
                    "status": current_run.status,
                    "reply_count": current_run.reply_count,
                    "awaiting_reply_until": _iso(current_run.awaiting_reply_until),
                    "no_reply_follow_up_sent_at": _iso(current_run.no_reply_follow_up_sent_at),
                },
            )
            sent += 1
    return {"sent": sent, "checked": len(rows)}
