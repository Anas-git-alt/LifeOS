"""Inbox-style intake capture and promotion services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.database import async_session
from app.models import IntakeEntry, IntakeEntryUpdate, LifeItem

FINAL_INTAKE_STATUSES = {"processed", "archived"}
PROMOTABLE_LIFE_ITEM_KINDS = {"task", "goal", "habit"}
DEFAULT_KIND_BY_INTAKE_KIND = {
    "idea": "task",
    "note": "task",
    "commitment": "task",
    "routine": "habit",
}


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_questions(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [question.strip() for question in value if str(question).strip()]
    if isinstance(value, str):
        return [line.strip("- ").strip() for line in value.splitlines() if line.strip()]
    return []


def _extract_questions_from_response(value: Any) -> list[str]:
    questions: list[str] = []
    for line in str(value or "").splitlines():
        text = line.strip().lstrip("-*• ").strip()
        if text.endswith("?"):
            questions.append(text)
    return questions[:3]


def _safe_domain(value: Any) -> str:
    candidate = str(value or "planning").strip().lower()
    if candidate in {"deen", "family", "work", "health", "planning"}:
        return candidate
    return "planning"


def _safe_status(value: Any) -> str:
    candidate = str(value or "raw").strip().lower()
    if candidate in {"raw", "clarifying", "ready", "processed", "parked", "archived"}:
        return candidate
    return "raw"


def _safe_kind(value: Any) -> str:
    candidate = str(value or "idea").strip().lower()
    if candidate in {"idea", "task", "goal", "habit", "commitment", "routine", "note"}:
        return candidate
    return "idea"


def _parse_date_string(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _build_entry_title(payload: dict[str, Any], user_message: str) -> str:
    title = _clean_text(payload.get("title"))
    if title:
        return title[:300]
    summary = _clean_text(payload.get("summary"))
    if summary:
        return summary[:300]
    raw = _clean_text(user_message) or "Captured idea"
    return raw[:300]


def _life_item_notes(entry: IntakeEntry, notes_override: str | None = None) -> str:
    parts = []
    if notes_override:
        parts.append(notes_override.strip())
    if entry.summary:
        parts.append(f"Summary: {entry.summary.strip()}")
    if entry.desired_outcome:
        parts.append(f"Desired outcome: {entry.desired_outcome.strip()}")
    if entry.next_action:
        parts.append(f"Suggested next action: {entry.next_action.strip()}")
    if entry.raw_text:
        parts.append(f"Captured from inbox: {entry.raw_text.strip()}")
    return "\n\n".join(part for part in parts if part)


async def list_intake_entries(
    status: str | None = None,
    session_id: int | None = None,
    limit: int = 100,
) -> list[IntakeEntry]:
    async with async_session() as db:
        query = select(IntakeEntry).order_by(IntakeEntry.updated_at.desc(), IntakeEntry.id.desc())
        if status:
            query = query.where(IntakeEntry.status == status)
        if session_id is not None:
            query = query.where(IntakeEntry.source_session_id == session_id)
        query = query.limit(max(1, min(limit, 200)))
        result = await db.execute(query)
        return list(result.scalars().all())


async def get_intake_entry(entry_id: int) -> IntakeEntry | None:
    async with async_session() as db:
        result = await db.execute(select(IntakeEntry).where(IntakeEntry.id == entry_id))
        return result.scalar_one_or_none()


async def get_latest_intake_entry_for_session(
    session_id: int,
    *,
    source_agent: str | None = None,
) -> IntakeEntry | None:
    async with async_session() as db:
        query = select(IntakeEntry).where(IntakeEntry.source_session_id == session_id)
        if source_agent:
            query = query.where(IntakeEntry.source_agent == source_agent)
        query = query.order_by(IntakeEntry.updated_at.desc(), IntakeEntry.id.desc()).limit(1)
        result = await db.execute(query)
        return result.scalar_one_or_none()


async def update_intake_entry(entry_id: int, data: IntakeEntryUpdate) -> IntakeEntry | None:
    async with async_session() as db:
        result = await db.execute(select(IntakeEntry).where(IntakeEntry.id == entry_id))
        entry = result.scalar_one_or_none()
        if not entry:
            return None

        updates = data.model_dump(exclude_unset=True)
        if "follow_up_questions" in updates:
            entry.follow_up_questions_json = _normalize_questions(updates.pop("follow_up_questions"))
        if "promotion_payload" in updates:
            entry.promotion_payload_json = updates.pop("promotion_payload")

        for key, value in updates.items():
            if key == "status":
                setattr(entry, key, _safe_status(value))
            elif key == "kind":
                setattr(entry, key, _safe_kind(value))
            elif key == "domain":
                setattr(entry, key, _safe_domain(value))
            else:
                setattr(entry, key, value)

        await db.commit()
        await db.refresh(entry)
        return entry


async def upsert_intake_entry_from_agent(
    *,
    payload: dict[str, Any],
    user_message: str,
    response_text: str,
    agent_name: str,
    session_id: int | None,
) -> IntakeEntry:
    async with async_session() as db:
        entry = None
        if session_id is not None:
            result = await db.execute(
                select(IntakeEntry)
                .where(
                    IntakeEntry.source_session_id == session_id,
                    IntakeEntry.source_agent == agent_name,
                    ~IntakeEntry.status.in_(FINAL_INTAKE_STATUSES),
                )
                .order_by(IntakeEntry.updated_at.desc(), IntakeEntry.id.desc())
                .limit(1)
            )
            entry = result.scalar_one_or_none()

        if not entry:
            entry = IntakeEntry(
                source="agent_capture",
                source_agent=agent_name,
                source_session_id=session_id,
                raw_text=_clean_text(user_message) or "Captured idea",
            )
            db.add(entry)

        entry.title = _build_entry_title(payload, user_message)
        entry.summary = _clean_text(payload.get("summary"))
        entry.domain = _safe_domain(payload.get("domain"))
        entry.kind = _safe_kind(payload.get("kind"))
        entry.status = _safe_status(payload.get("status"))
        entry.desired_outcome = _clean_text(payload.get("desired_outcome"))
        entry.next_action = _clean_text(payload.get("next_action"))
        entry.follow_up_questions_json = _normalize_questions(payload.get("follow_up_questions"))
        entry.structured_data_json = dict(payload)
        promotion_payload = payload.get("life_item")
        entry.promotion_payload_json = promotion_payload if isinstance(promotion_payload, dict) else None
        entry.last_agent_response = _clean_text(response_text)
        if not entry.raw_text:
            entry.raw_text = _clean_text(user_message) or "Captured idea"

        await db.commit()
        await db.refresh(entry)
        return entry


async def upsert_fallback_intake_entry(
    *,
    user_message: str,
    response_text: str,
    agent_name: str,
    session_id: int | None,
    reason: str = "missing_intake_json",
) -> IntakeEntry:
    async with async_session() as db:
        entry = None
        if session_id is not None:
            result = await db.execute(
                select(IntakeEntry)
                .where(
                    IntakeEntry.source_session_id == session_id,
                    IntakeEntry.source_agent == agent_name,
                    ~IntakeEntry.status.in_(FINAL_INTAKE_STATUSES),
                )
                .order_by(IntakeEntry.updated_at.desc(), IntakeEntry.id.desc())
                .limit(1)
            )
            entry = result.scalar_one_or_none()

        if not entry:
            entry = IntakeEntry(
                source="agent_capture",
                source_agent=agent_name,
                source_session_id=session_id,
                raw_text=_clean_text(user_message) or "Captured idea",
            )
            db.add(entry)

        cleaned_response = _clean_text(response_text)
        if not entry.raw_text:
            entry.raw_text = _clean_text(user_message) or "Captured idea"
        entry.title = (entry.title or _clean_text(user_message) or "Captured idea")[:300]
        if cleaned_response and not entry.summary:
            entry.summary = cleaned_response[:500]
        entry.domain = entry.domain or "planning"
        entry.kind = entry.kind or "idea"
        entry.status = "clarifying"
        entry.follow_up_questions_json = _extract_questions_from_response(cleaned_response)
        entry.last_agent_response = cleaned_response
        entry.structured_data_json = {"fallback_reason": reason}
        if not entry.promotion_payload_json:
            entry.promotion_payload_json = None

        await db.commit()
        await db.refresh(entry)
        return entry


async def promote_intake_entry(
    entry_id: int,
    overrides: dict[str, Any] | None = None,
) -> tuple[IntakeEntry | None, LifeItem | None]:
    overrides = overrides or {}
    async with async_session() as db:
        result = await db.execute(select(IntakeEntry).where(IntakeEntry.id == entry_id))
        entry = result.scalar_one_or_none()
        if not entry:
            return None, None

        payload = dict(entry.promotion_payload_json or {})
        payload.update({key: value for key, value in overrides.items() if value not in (None, "")})

        title = _clean_text(payload.get("title")) or _clean_text(entry.title) or "Captured action"
        item_kind = _safe_kind(payload.get("kind") or entry.kind)
        life_item_kind = item_kind if item_kind in PROMOTABLE_LIFE_ITEM_KINDS else DEFAULT_KIND_BY_INTAKE_KIND.get(item_kind, "task")
        start_date = _parse_date_string(payload.get("start_date"))

        item = LifeItem(
            domain=_safe_domain(payload.get("domain") or entry.domain),
            title=title,
            kind=life_item_kind,
            notes=_life_item_notes(entry, notes_override=_clean_text(payload.get("notes"))),
            priority=str(payload.get("priority") or "medium").strip().lower() or "medium",
            due_at=payload.get("due_at"),
            start_date=start_date,
            recurrence_rule=_clean_text(payload.get("recurrence_rule")),
            source_agent=entry.source_agent,
            risk_level="low",
        )
        db.add(item)
        await db.flush()

        entry.linked_life_item_id = item.id
        entry.status = "processed"
        entry.next_action = _clean_text(payload.get("next_action")) or entry.next_action
        entry.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(entry)
        await db.refresh(item)
        return entry, item


async def get_intake_summary() -> dict[str, int]:
    async with async_session() as db:
        result = await db.execute(
            select(IntakeEntry.status, func.count(IntakeEntry.id))
            .group_by(IntakeEntry.status)
        )
        return {status: count for status, count in result.all()}
