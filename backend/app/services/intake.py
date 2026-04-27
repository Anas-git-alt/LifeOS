"""Inbox-style intake capture and promotion services."""

from __future__ import annotations

from datetime import datetime, timezone
import re
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


def _looks_ready_to_track(value: Any) -> bool:
    text = str(value or "").lower()
    ready_phrases = [
        "ready to track",
        "ready to promote",
        "ready for tracking",
        "ready to create",
        "ready. reminder",
    ]
    if any(phrase in text for phrase in ready_phrases):
        return True
    return "ready" in text and "need clarification" not in text and "not ready" not in text


def _infer_domain_from_text(value: Any) -> str:
    text = str(value or "").lower()
    if any(token in text for token in ["invoice", "payment", "client", "presentation", "one pager", "video", "mockup", "canva", "work"]):
        return "work"
    if any(token in text for token in ["pray", "quran", "deen", "salah"]):
        return "deen"
    if any(token in text for token in ["wife", "family", "kids", "home"]):
        return "family"
    if any(token in text for token in ["sleep", "workout", "gym", "health", "meal"]):
        return "health"
    return "planning"


def _extract_commitment_title(response_text: Any, user_message: str) -> str:
    for line in str(response_text or "").splitlines():
        text = line.strip().lstrip("-*• ").strip()
        if text.lower().startswith("commitment:"):
            title = text.split(":", 1)[1].strip()
            title = title.removesuffix(".").strip()
            if title:
                return title[:300]
    return (_clean_text(user_message) or "Captured commitment")[:300]


def _safe_domain(value: Any) -> str:
    candidate = str(value or "planning").strip().lower()
    if "|" in candidate:
        return "planning"
    if candidate in {"deen", "family", "work", "health", "planning"}:
        return candidate
    return "planning"


def _safe_status(value: Any) -> str:
    candidate = str(value or "raw").strip().lower()
    if "|" in candidate:
        return "clarifying"
    if candidate in {"raw", "clarifying", "ready", "processed", "parked", "archived"}:
        return candidate
    return "raw"


def _safe_kind(value: Any) -> str:
    candidate = str(value or "idea").strip().lower()
    if "|" in candidate:
        return "idea"
    if candidate in {"idea", "task", "goal", "habit", "commitment", "routine", "note"}:
        return candidate
    return "idea"


def _parse_date_string(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_datetime_value(value):
    if isinstance(value, datetime):
        return value
    text = _clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _coerce_priority_score(value: Any) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return 50


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


def _normalize_life_item_title(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\buat[-\s]*\d{4}-\d{2}-\d{2}[-\w]*:?", " ", text)
    text = re.sub(r"\buat\s+timezone:?", " ", text)
    text = re.sub(r"\bremind\s+me\s+(?:to\s+)?", " ", text)
    text = re.sub(r"\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", " ", text)
    text = re.sub(r"\b(?:at|by|before)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _same_due_time(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    left_utc = left.replace(tzinfo=timezone.utc) if left.tzinfo is None else left.astimezone(timezone.utc)
    right_utc = right.replace(tzinfo=timezone.utc) if right.tzinfo is None else right.astimezone(timezone.utc)
    return abs((left_utc - right_utc).total_seconds()) <= 60


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
    primary_payload = payload
    if isinstance(payload.get("items"), list) and payload["items"]:
        first_item = next((item for item in payload["items"] if isinstance(item, dict)), None)
        if first_item:
            primary_payload = {**payload, **first_item}

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
                result = await db.execute(
                    select(IntakeEntry)
                    .where(
                        IntakeEntry.source_session_id == session_id,
                        IntakeEntry.source_agent == agent_name,
                        IntakeEntry.linked_life_item_id.is_not(None),
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

        entry.title = _build_entry_title(primary_payload, user_message)
        entry.summary = _clean_text(primary_payload.get("summary"))
        entry.domain = _safe_domain(primary_payload.get("domain"))
        entry.kind = _safe_kind(primary_payload.get("kind"))
        entry.status = _safe_status(primary_payload.get("status"))
        entry.desired_outcome = _clean_text(primary_payload.get("desired_outcome"))
        entry.next_action = _clean_text(primary_payload.get("next_action"))
        entry.follow_up_questions_json = _normalize_questions(primary_payload.get("follow_up_questions"))
        entry.structured_data_json = dict(payload)
        promotion_payload = primary_payload.get("life_item")
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
                result = await db.execute(
                    select(IntakeEntry)
                    .where(
                        IntakeEntry.source_session_id == session_id,
                        IntakeEntry.source_agent == agent_name,
                        IntakeEntry.linked_life_item_id.is_not(None),
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
        if entry.linked_life_item_id:
            entry.last_agent_response = cleaned_response
            entry.structured_data_json = {"fallback_reason": reason, "reused_linked_entry": True}
            await db.commit()
            await db.refresh(entry)
            return entry

        if not entry.raw_text:
            entry.raw_text = _clean_text(user_message) or "Captured idea"
        ready_commitment = agent_name == "commitment-capture" and _looks_ready_to_track(cleaned_response)
        entry.title = (
            _extract_commitment_title(cleaned_response, user_message)
            if ready_commitment
            else (entry.title or _clean_text(user_message) or "Captured idea")[:300]
        )
        if cleaned_response and not entry.summary:
            entry.summary = cleaned_response[:500]
        if ready_commitment:
            domain = _infer_domain_from_text(f"{entry.title} {user_message} {cleaned_response}")
            entry.domain = domain
            entry.kind = "commitment"
            entry.status = "ready"
            entry.follow_up_questions_json = []
            entry.promotion_payload_json = {
                "title": entry.title,
                "kind": "task",
                "domain": domain,
                "priority": "medium",
                "next_action": entry.title,
            }
        else:
            entry.domain = entry.domain or "planning"
            entry.kind = entry.kind or "idea"
            entry.status = "clarifying"
            entry.follow_up_questions_json = _extract_questions_from_response(cleaned_response)
        entry.last_agent_response = cleaned_response
        entry.structured_data_json = {"fallback_reason": reason}
        if not ready_commitment and not entry.promotion_payload_json:
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
        due_at = _parse_datetime_value(payload.get("due_at"))
        normalized_title = _normalize_life_item_title(title)
        if normalized_title:
            existing_result = await db.execute(
                select(LifeItem).where(
                    LifeItem.status == "open",
                    LifeItem.kind == life_item_kind,
                )
            )
            for existing in existing_result.scalars().all():
                if _normalize_life_item_title(existing.title) == normalized_title and _same_due_time(existing.due_at, due_at):
                    entry.linked_life_item_id = existing.id
                    entry.status = "processed"
                    entry.next_action = _clean_text(payload.get("next_action")) or entry.next_action
                    entry.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    await db.refresh(entry)
                    await db.refresh(existing)
                    return entry, existing

        item = LifeItem(
            domain=_safe_domain(payload.get("domain") or entry.domain),
            title=title,
            kind=life_item_kind,
            notes=_life_item_notes(entry, notes_override=_clean_text(payload.get("notes"))),
            priority=str(payload.get("priority") or "medium").strip().lower() or "medium",
            due_at=due_at,
            start_date=start_date,
            recurrence_rule=_clean_text(payload.get("recurrence_rule")),
            source_agent=entry.source_agent,
            risk_level="low",
            priority_score=_coerce_priority_score(payload.get("priority_score")),
            priority_reason=_clean_text(payload.get("priority_reason")),
            priority_factors_json=payload.get("priority_factors") if isinstance(payload.get("priority_factors"), dict) else None,
            context_links_json=payload.get("context_links") if isinstance(payload.get("context_links"), list) else None,
            last_prioritized_at=_parse_datetime_value(payload.get("last_prioritized_at")),
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
