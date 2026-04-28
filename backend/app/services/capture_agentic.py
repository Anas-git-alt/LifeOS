"""Agentic capture planner, critic, executor, and correction memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import async_session
from app.models import (
    CaptureCorrection,
    CaptureCorrectionResponse,
    CaptureItemPlan,
    CaptureItemResponse,
    CapturePlan,
    CapturePlanCriticResponse,
    CapturePlanDocumentResponse,
    CapturePlanItemResponse,
    CaptureRoutedResultResponse,
    ContextEvent,
    ContextEventResponse,
    DailyLogCreate,
    IntakeEntry,
    IntakeEntryResponse,
    LifeItem,
    LifeItemCreate,
    LifeItemResponse,
    LifeItemUpdate,
    MeetingIntakeRequest,
    PrayerRetroactiveCheckinRequest,
    RawCapture,
    ScheduledJobResponse,
    SharedMemoryPromoteRequest,
    SharedMemoryProposal,
    SharedMemoryProposalResponse,
)
from app.services.chat_sessions import create_session, generate_title_from_prompts
from app.services.commitments import disable_follow_up_job, get_commitment_timezone, upsert_follow_up_job
from app.services.context_events import capture_meeting_summary
from app.services.intake import update_intake_entry
from app.services.life import create_life_item, log_daily_signal, update_life_item
from app.services.prayer_service import get_today_schedule, log_prayer_checkin_retroactive
from app.services.provider_router import chat_completion
from app.services.shared_memory import create_shared_memory_review_proposal

PLANNER_PROVIDER = "openrouter"
PLANNER_MODEL = "minimax/minimax-m2.5:free"
PLANNER_FALLBACK_PROVIDER = "nvidia"
PLANNER_FALLBACK_MODEL = "meta/llama-3.1-8b-instruct"
CRITIC_PROVIDER = "openrouter"
CRITIC_MODEL = "minimax/minimax-m2.5:free"
CRITIC_FALLBACK_PROVIDER = "nvidia"
CRITIC_FALLBACK_MODEL = "meta/llama-3.1-8b-instruct"
CORRECTION_PROVIDER = "openrouter"
CORRECTION_MODEL = "minimax/minimax-m2.5:free"
CORRECTION_FALLBACK_PROVIDER = "nvidia"
CORRECTION_FALLBACK_MODEL = "meta/llama-3.1-8b-instruct"
CAPTURE_INTENTS = {
    "commitment",
    "reminder",
    "memory",
    "preference",
    "task",
    "goal",
    "habit",
    "routine",
    "daily_log",
    "meeting_note",
    "question",
    "idea",
    "correction",
}
CAPTURE_DESTINATIONS = {"life_item", "memory_review", "daily_log", "needs_answer", "context_event", "no_action"}
CAPTURE_DOMAINS = {"deen", "family", "work", "health", "planning"}
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
TIME_PHRASE_RE = re.compile(
    r"\b(today|tomorrow)\s+(?:at|by|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)
BY_TIME_RE = re.compile(
    r"\bby\s+(today|tomorrow)\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)
REVERSE_TIME_RE = re.compile(
    r"\b(?:at|by|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(today|tomorrow)\b",
    re.IGNORECASE,
)
STANDALONE_TIME_RE = re.compile(
    r"\b(?:at|by|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
WEEKDAY_CLOCK_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b"
    r"(?:\s+(?:at|by|before))?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
WEEKDAY_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)
DATE_MONTH_RE = re.compile(
    r"\b(?:next\s+)?(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)?\s*"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)
SLEEP_HOURS_RE = re.compile(r"\b(?:slept?|sleep)\b[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\b", re.IGNORECASE)
BEDTIME_RE = re.compile(r"\b(?:bed(?:time)?|slept?\s+at)\s+(\d{1,2}:\d{2})\b", re.IGNORECASE)
WAKE_RE = re.compile(r"\b(?:wake(?:\s*time)?|woke\s+up\s+at)\s+(\d{1,2}:\d{2})\b", re.IGNORECASE)
TRAINING_DONE_RE = re.compile(r"\b(trained|training done|workout done|gym done|lifted)\b", re.IGNORECASE)
TRAINING_REST_RE = re.compile(r"\b(rest day|rested|training rest)\b", re.IGNORECASE)
TRAINING_MISSED_RE = re.compile(r"\b(missed training|skipped training|no workout)\b", re.IGNORECASE)
PRAYER_NAME_RE = re.compile(r"\b(Fajr|Dhuhr|Asr|Maghrib|Isha)\b", re.IGNORECASE)
PRAYER_MISSED_RE = re.compile(r"\b(missed|skip(?:ped)?)\b", re.IGNORECASE)
PRAYER_LATE_RE = re.compile(r"\b(late)\b", re.IGNORECASE)
PRAYER_DONE_RE = re.compile(r"\b(prayed|done|on time|made it)\b", re.IGNORECASE)
WATER_COUNT_RE = re.compile(r"\b(\d+)\s*(?:cup|cups|glass|glasses|bottle|bottles)\b", re.IGNORECASE)
MEAL_RE = re.compile(r"\b(ate|meal|breakfast|lunch|dinner|food)\b", re.IGNORECASE)
WATER_RE = re.compile(r"\b(water|hydration|drank|drink|cup|cups|glass|glasses|bottle|bottles)\b", re.IGNORECASE)
STOP_WORDS = {
    "that",
    "this",
    "with",
    "from",
    "your",
    "their",
    "have",
    "need",
    "needs",
    "want",
    "wants",
    "should",
    "could",
    "would",
    "into",
    "about",
    "after",
    "before",
    "make",
    "made",
}


@dataclass
class CaptureExecutionBundle:
    raw_capture: RawCapture
    capture_plan_row: CapturePlan
    capture_plan: CapturePlanDocumentResponse
    critic: CapturePlanCriticResponse
    capture_items: list[CaptureItemResponse]
    routed_results: list[CaptureRoutedResultResponse]
    entries: list[IntakeEntryResponse]
    life_items: list[LifeItemResponse]
    wiki_proposals: list[SharedMemoryProposalResponse]
    first_follow_up_job: ScheduledJobResponse | None
    first_event: ContextEventResponse | None
    logged_signals: list[str]
    completed_items: list[LifeItemResponse]
    corrections: list[CaptureCorrectionResponse]
    audit_summary: str
    session_id: int | None
    session_title: str | None


def _clean_text(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").strip().split())
    if limit is not None:
        return text[:limit]
    return text


def _extract_json(text: str) -> dict[str, Any] | None:
    block = str(text or "").strip()
    if not block:
        return None
    match = JSON_BLOCK_RE.search(block)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tokenize(text: str) -> set[str]:
    return {token for token in WORD_RE.findall(str(text or "").lower()) if token not in STOP_WORDS}


def _safe_destination(value: Any) -> str:
    lowered = str(value or "needs_answer").strip().lower()
    return lowered if lowered in CAPTURE_DESTINATIONS else "needs_answer"


def _safe_domain(value: Any) -> str:
    lowered = str(value or "planning").strip().lower()
    return lowered if lowered in CAPTURE_DOMAINS else "planning"


def _safe_intent(value: Any) -> str:
    lowered = str(value or "idea").strip().lower()
    return lowered if lowered in CAPTURE_INTENTS else "idea"


def _safe_questions(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(item, limit=240) for item in value if _clean_text(item)]
    if isinstance(value, str):
        return [_clean_text(value, limit=240)] if _clean_text(value) else []
    return []


def _safe_confidence(value: Any, *, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1:
        number = number / 100.0
    return max(0.0, min(number, 1.0))


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc)


def _resolve_tz(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or "Africa/Casablanca")
    except Exception:
        return ZoneInfo("Africa/Casablanca")


def _parse_capture_clock(hour_text: str, minute_text: str | None, meridian_text: str | None) -> tuple[int, int] | None:
    hour = int(hour_text)
    minute = int(minute_text or 0)
    meridian = (meridian_text or "").lower()
    if meridian == "pm" and hour < 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _default_clock_for_text(text: str) -> tuple[int, int]:
    lowered = str(text or "").lower()
    if "morning" in lowered:
        return 9, 0
    if "afternoon" in lowered:
        return 14, 0
    if "evening" in lowered or "night" in lowered:
        return 18, 0
    return 9, 0


def _month_number(value: str) -> int | None:
    return {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }.get(str(value or "").lower()[:3])


def _due_from_capture_match(match: re.Match[str], *, timezone_name: str, now_utc: datetime | None = None) -> datetime | None:
    clock = _parse_capture_clock(match.group(2), match.group(3), match.group(4))
    if not clock:
        return None
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    due_date = local_now.date() + timedelta(days=1 if match.group(1).lower() == "tomorrow" else 0)
    return datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1]).astimezone(timezone.utc)


def _due_from_reverse_capture_match(match: re.Match[str], *, timezone_name: str, now_utc: datetime | None = None) -> datetime | None:
    clock = _parse_capture_clock(match.group(1), match.group(2), match.group(3))
    if not clock:
        return None
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    due_date = local_now.date() + timedelta(days=1 if match.group(4).lower() == "tomorrow" else 0)
    return datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1]).astimezone(timezone.utc)


def _standalone_due_from_capture_match(
    match: re.Match[str],
    *,
    text: str,
    timezone_name: str,
    now_utc: datetime | None = None,
) -> datetime | None:
    lowered = str(text or "").lower()
    if "today" not in lowered and "tomorrow" not in lowered:
        return None
    clock = _parse_capture_clock(match.group(1), match.group(2), match.group(3))
    if not clock:
        return None
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    due_date = local_now.date() + timedelta(days=1 if "tomorrow" in lowered and "today" not in lowered else 0)
    return datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1]).astimezone(timezone.utc)


def _date_month_due_from_text(text: str, *, timezone_name: str, now_utc: datetime | None = None) -> datetime | None:
    match = DATE_MONTH_RE.search(text or "")
    if not match:
        return None
    month = _month_number(match.group(2))
    if not month:
        return None
    day = int(match.group(1))
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    year = local_now.year
    try:
        due_local = datetime(year, month, day, tzinfo=tz)
    except ValueError:
        return None
    if due_local.date() < local_now.date():
        try:
            due_local = due_local.replace(year=year + 1)
        except ValueError:
            return None
    clock_match = STANDALONE_TIME_RE.search(text or "")
    clock = (
        _parse_capture_clock(clock_match.group(1), clock_match.group(2), clock_match.group(3))
        if clock_match
        else _default_clock_for_text(text)
    )
    return due_local.replace(hour=clock[0], minute=clock[1]).astimezone(timezone.utc) if clock else None


def _weekday_due_from_text(text: str, *, timezone_name: str, now_utc: datetime | None = None) -> datetime | None:
    weekday_match = WEEKDAY_RE.search(text or "")
    if not weekday_match:
        return None
    weekday_lookup = {
        "mon": 0,
        "monday": 0,
        "tue": 1,
        "tuesday": 1,
        "wed": 2,
        "wednesday": 2,
        "thu": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
        "sat": 5,
        "saturday": 5,
        "sun": 6,
        "sunday": 6,
    }
    target_weekday = weekday_lookup.get(weekday_match.group(1).lower())
    if target_weekday is None:
        return None
    weekday_clock = WEEKDAY_CLOCK_RE.search(text or "")
    clock_match = STANDALONE_TIME_RE.search(text or "")
    if weekday_clock:
        clock = _parse_capture_clock(weekday_clock.group(2), weekday_clock.group(3), weekday_clock.group(4))
    elif clock_match:
        clock = _parse_capture_clock(clock_match.group(1), clock_match.group(2), clock_match.group(3))
    else:
        clock = _default_clock_for_text(text)
    if not clock:
        return None
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    days_ahead = (target_weekday - local_now.weekday()) % 7
    due_date = local_now.date() + timedelta(days=days_ahead)
    due_local = datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1])
    if due_local <= local_now:
        due_local += timedelta(days=7)
    return due_local.astimezone(timezone.utc)


async def normalize_due_expression(
    due_expression: str | None,
    *,
    provided_due_at: datetime | None,
    timezone_name: str | None,
    now_utc: datetime | None = None,
) -> datetime | None:
    if provided_due_at is not None:
        return provided_due_at if provided_due_at.tzinfo else provided_due_at.replace(tzinfo=timezone.utc)
    text = str(due_expression or "").strip()
    if not text:
        return None
    effective_timezone = await get_commitment_timezone(timezone_name)
    match = TIME_PHRASE_RE.search(text)
    if match:
        return _due_from_capture_match(match, timezone_name=effective_timezone, now_utc=now_utc)
    match = BY_TIME_RE.search(text)
    if match:
        return _due_from_capture_match(match, timezone_name=effective_timezone, now_utc=now_utc)
    match = REVERSE_TIME_RE.search(text)
    if match:
        return _due_from_reverse_capture_match(match, timezone_name=effective_timezone, now_utc=now_utc)
    match = STANDALONE_TIME_RE.search(text)
    if match:
        standalone = _standalone_due_from_capture_match(match, text=text, timezone_name=effective_timezone, now_utc=now_utc)
        if standalone:
            return standalone
    explicit_date = _date_month_due_from_text(text, timezone_name=effective_timezone, now_utc=now_utc)
    if explicit_date:
        return explicit_date
    return _weekday_due_from_text(text, timezone_name=effective_timezone, now_utc=now_utc)


def _fallback_plan(message: str) -> CapturePlanDocumentResponse:
    source_span = _clean_text(message, limit=500)
    return CapturePlanDocumentResponse(
        items=[
            CapturePlanItemResponse(
                title=_clean_text(message, limit=120) or "Capture needs review",
                summary="LifeOS needs clarification before safe execution.",
                user_intent="idea",
                destination="needs_answer",
                domain="planning",
                kind="idea",
                due_at=None,
                due_expression=None,
                recurrence=None,
                should_schedule_reminder=False,
                should_appear_in_focus=False,
                needs_clarification=True,
                questions=["What should LifeOS do with this capture?"],
                confidence=0.2,
                reasoning_summary="Planner output missing or invalid.",
                source_span=source_span or "Capture needs review",
                execution_status="planned",
                linked_entity_type=None,
                linked_entity_id=None,
                execution_metadata=None,
            )
        ],
        uncaptured_residue=[],
        overall_confidence=0.2,
        user_visible_summary="Captured raw message. Needs answer before tracking.",
    )


def _normalize_plan_item(raw: dict[str, Any], message: str) -> CapturePlanItemResponse:
    source_span = _clean_text(raw.get("source_span") or message, limit=500)
    questions = _safe_questions(raw.get("questions"))
    destination = _safe_destination(raw.get("destination"))
    confidence = _safe_confidence(raw.get("confidence"), default=0.55)
    should_schedule_reminder = bool(raw.get("should_schedule_reminder"))
    if should_schedule_reminder and destination == "no_action":
        should_schedule_reminder = False
    return CapturePlanItemResponse(
        id=raw.get("id"),
        title=_clean_text(raw.get("title"), limit=300) or _clean_text(source_span, limit=120) or "Captured item",
        summary=_clean_text(raw.get("summary"), limit=1000) or _clean_text(source_span, limit=1000) or "Captured item",
        user_intent=_safe_intent(raw.get("user_intent")),
        destination=destination,
        domain=_safe_domain(raw.get("domain")),
        kind=_clean_text(raw.get("kind"), limit=60) or _safe_intent(raw.get("user_intent")),
        due_at=_parse_datetime(raw.get("due_at")),
        due_expression=_clean_text(raw.get("due_expression"), limit=300),
        recurrence=_clean_text(raw.get("recurrence"), limit=240) or None,
        should_schedule_reminder=should_schedule_reminder,
        should_appear_in_focus=bool(raw.get("should_appear_in_focus")),
        needs_clarification=bool(raw.get("needs_clarification")) or bool(questions),
        questions=questions[:4],
        confidence=confidence,
        reasoning_summary=_clean_text(raw.get("reasoning_summary"), limit=600) or "",
        source_span=source_span or _clean_text(message, limit=500) or "Captured item",
        execution_status=_clean_text(raw.get("execution_status"), limit=30) or None,
        linked_entity_type=_clean_text(raw.get("linked_entity_type"), limit=40) or None,
        linked_entity_id=raw.get("linked_entity_id"),
        execution_metadata=raw.get("execution_metadata") if isinstance(raw.get("execution_metadata"), dict) else None,
    )


def _normalize_plan_document(parsed: dict[str, Any] | None, message: str) -> CapturePlanDocumentResponse:
    if not parsed:
        return _fallback_plan(message)
    raw_items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    items = [_normalize_plan_item(item, message) for item in raw_items if isinstance(item, dict)]
    if not items:
        return _fallback_plan(message)
    residue = [_clean_text(item, limit=500) for item in (parsed.get("uncaptured_residue") or []) if _clean_text(item)]
    return CapturePlanDocumentResponse(
        items=items[:12],
        uncaptured_residue=residue[:8],
        overall_confidence=_safe_confidence(parsed.get("overall_confidence"), default=max(item.confidence for item in items)),
        user_visible_summary=_clean_text(parsed.get("user_visible_summary"), limit=500)
        or f"Captured {len(items)} item{'s' if len(items) != 1 else ''}.",
    )


def _normalize_critic_document(parsed: dict[str, Any] | None, message: str, planner_plan: CapturePlanDocumentResponse) -> CapturePlanCriticResponse:
    if not parsed:
        return CapturePlanCriticResponse(approved=True, issues=[], final_plan=planner_plan, critic_summary="Critic fallback.")
    final_plan = _normalize_plan_document(parsed.get("final_plan") if isinstance(parsed.get("final_plan"), dict) else parsed, message)
    return CapturePlanCriticResponse(
        approved=bool(parsed.get("approved", True)),
        issues=[_clean_text(item, limit=240) for item in (parsed.get("issues") or []) if _clean_text(item)],
        final_plan=final_plan,
        critic_summary=_clean_text(parsed.get("critic_summary"), limit=500) or "",
    )


def _correction_examples_text(examples: list[CaptureCorrection]) -> str:
    if not examples:
        return "None."
    lines = []
    for idx, example in enumerate(examples[:4], start=1):
        lines.append(
            f"{idx}. Correction: {example.user_correction_text}\n"
            f"Lesson: {_clean_text(example.lesson, limit=240) or 'none'}\n"
            f"Before: {json.dumps(example.previous_plan_json or {}, ensure_ascii=True)[:600]}\n"
            f"After: {json.dumps(example.corrected_plan_json or {}, ensure_ascii=True)[:600]}"
        )
    return "\n\n".join(lines)


async def ensure_capture_session(message: str, session_id: int | None, *, new_session: bool) -> tuple[int | None, str | None]:
    if session_id:
        return session_id, None
    if not new_session:
        return None, None
    title = generate_title_from_prompts([message])
    session = await create_session(agent_name="intake-inbox", title=title)
    return session.id, session.title


async def create_raw_capture(
    *,
    message: str,
    source: str,
    session_id: int | None,
    source_message_id: str | None,
    source_channel_id: str | None,
    status: str = "received",
    metadata: dict[str, Any] | None = None,
) -> RawCapture:
    async with async_session() as db:
        row = RawCapture(
            raw_text=message,
            source=source or "api",
            source_message_id=source_message_id,
            source_channel_id=source_channel_id,
            session_id=session_id,
            status=status,
            metadata_json=metadata or None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def update_raw_capture(
    raw_capture_id: int,
    *,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> RawCapture | None:
    async with async_session() as db:
        row = await db.get(RawCapture, raw_capture_id)
        if not row:
            return None
        row.status = status
        row.processed_at = datetime.now(timezone.utc)
        if metadata:
            current = dict(row.metadata_json or {})
            current.update(metadata)
            row.metadata_json = current
        await db.commit()
        await db.refresh(row)
        return row


async def _list_relevant_corrections(message: str, *, limit: int = 4) -> list[CaptureCorrection]:
    tokens = _tokenize(message)
    if not tokens:
        return []
    async with async_session() as db:
        result = await db.execute(select(CaptureCorrection).order_by(CaptureCorrection.created_at.desc()).limit(80))
        rows = list(result.scalars().all())
    scored: list[tuple[float, CaptureCorrection]] = []
    for row in rows:
        haystack = " ".join(
            [
                str(row.user_correction_text or ""),
                str(row.lesson or ""),
                json.dumps(row.previous_plan_json or {}, ensure_ascii=True),
                json.dumps(row.corrected_plan_json or {}, ensure_ascii=True),
            ]
        )
        overlap = tokens.intersection(_tokenize(haystack))
        if overlap:
            scored.append((len(overlap) / max(1, len(tokens)), row))
    scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
    return [row for _, row in scored[:limit]]


def _planner_prompt(
    *,
    message: str,
    timezone_name: str,
    route_hint: str | None,
    examples: list[CaptureCorrection],
) -> str:
    return (
        "You are LifeOS AI Capture Planner.\n"
        "Interpret messy natural input into safe capture plan.\n"
        "Return JSON only.\n"
        "Schema:\n"
        "{"
        "\"items\":[{"
        "\"title\":\"...\","
        "\"summary\":\"...\","
        "\"user_intent\":\"commitment|reminder|memory|preference|task|goal|habit|routine|daily_log|meeting_note|question|idea|correction\","
        "\"destination\":\"life_item|memory_review|daily_log|needs_answer|context_event|no_action\","
        "\"domain\":\"deen|family|work|health|planning\","
        "\"kind\":\"...\","
        "\"due_at\":\"ISO-8601 datetime or null\","
        "\"due_expression\":\"exact due phrase or null\","
        "\"recurrence\":\"string or null\","
        "\"should_schedule_reminder\":false,"
        "\"should_appear_in_focus\":false,"
        "\"needs_clarification\":false,"
        "\"questions\":[],"
        "\"confidence\":0.0,"
        "\"reasoning_summary\":\"short honest reason\","
        "\"source_span\":\"exact text span\""
        "}],"
        "\"uncaptured_residue\":[\"...\"],"
        "\"overall_confidence\":0.0,"
        "\"user_visible_summary\":\"...\""
        "}\n"
        "Rules:\n"
        "- Capture every meaningful item.\n"
        "- AI decides meaning and destination.\n"
        "- Do not turn preferences or durable memories into tasks.\n"
        "- Do not turn future reminders into daily logs.\n"
        "- Avoid focus pollution. should_appear_in_focus=true only for few truly current items.\n"
        "- Do not invent urgency.\n"
        "- Preserve source truth. source_span exact.\n"
        "- If uncertain, use needs_clarification=true, destination=needs_answer, ask sharp question.\n"
        "- Use no_action only when user explicitly wants no tracked action.\n"
        "- For daily logs, split separate sleep/meal/hydration/training/prayer items when present.\n"
        "- For reminders or commitments with date text, copy exact due phrase into due_expression.\n"
        "- Honest user_visible_summary only. No fake certainty.\n"
        f"Local timezone: {timezone_name}.\n"
        f"Route hint: {route_hint or 'auto'}.\n"
        "Relevant prior correction lessons:\n"
        f"{_correction_examples_text(examples)}\n"
        "User message:\n"
        f"{message}"
    )


def _critic_prompt(
    *,
    message: str,
    planner_plan: CapturePlanDocumentResponse,
    timezone_name: str,
) -> str:
    return (
        "You are LifeOS AI Capture Critic.\n"
        "Review planner output before execution. Return JSON only.\n"
        "Schema:\n"
        "{"
        "\"approved\":true,"
        "\"issues\":[\"...\"],"
        "\"critic_summary\":\"...\","
        "\"final_plan\":{"
        "\"items\":[{"
        "\"title\":\"...\","
        "\"summary\":\"...\","
        "\"user_intent\":\"commitment|reminder|memory|preference|task|goal|habit|routine|daily_log|meeting_note|question|idea|correction\","
        "\"destination\":\"life_item|memory_review|daily_log|needs_answer|context_event|no_action\","
        "\"domain\":\"deen|family|work|health|planning\","
        "\"kind\":\"...\","
        "\"due_at\":\"ISO-8601 datetime or null\","
        "\"due_expression\":\"exact due phrase or null\","
        "\"recurrence\":\"string or null\","
        "\"should_schedule_reminder\":false,"
        "\"should_appear_in_focus\":false,"
        "\"needs_clarification\":false,"
        "\"questions\":[],"
        "\"confidence\":0.0,"
        "\"reasoning_summary\":\"...\","
        "\"source_span\":\"exact text span\""
        "}],"
        "\"uncaptured_residue\":[\"...\"],"
        "\"overall_confidence\":0.0,"
        "\"user_visible_summary\":\"...\""
        "}"
        "}\n"
        "Check:\n"
        "- every meaningful item captured\n"
        "- no preference/memory accidentally turned into task\n"
        "- no future reminder turned into daily log\n"
        "- no focus pollution\n"
        "- no fake urgency\n"
        "- clarification asked when needed\n"
        "- source truth preserved\n"
        "- user summary honest\n"
        f"Local timezone: {timezone_name}.\n"
        f"Raw message:\n{message}\n\n"
        f"Planner plan:\n{planner_plan.model_dump_json()}"
    )


async def plan_capture_text(
    *,
    message: str,
    timezone_name: str | None,
    route_hint: str | None = None,
) -> tuple[CapturePlanDocumentResponse, CapturePlanCriticResponse]:
    effective_timezone = await get_commitment_timezone(timezone_name)
    examples = await _list_relevant_corrections(message)
    raw = await chat_completion(
        messages=[
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": _planner_prompt(message=message, timezone_name=effective_timezone, route_hint=route_hint, examples=examples)},
        ],
        provider=PLANNER_PROVIDER,
        model=PLANNER_MODEL,
        fallback_provider=PLANNER_FALLBACK_PROVIDER,
        fallback_model=PLANNER_FALLBACK_MODEL,
        temperature=0.1,
        max_tokens=2200,
    )
    planner_plan = _normalize_plan_document(_extract_json(str(raw or "")), message)
    critic_raw = await chat_completion(
        messages=[
            {"role": "system", "content": "Return strict JSON only."},
            {"role": "user", "content": _critic_prompt(message=message, planner_plan=planner_plan, timezone_name=effective_timezone)},
        ],
        provider=CRITIC_PROVIDER,
        model=CRITIC_MODEL,
        fallback_provider=CRITIC_FALLBACK_PROVIDER,
        fallback_model=CRITIC_FALLBACK_MODEL,
        temperature=0.0,
        max_tokens=2200,
    )
    critic = _normalize_critic_document(_extract_json(str(critic_raw or "")), message, planner_plan)
    return planner_plan, critic


def _capture_item_type_from_plan(item: CapturePlanItemResponse) -> str:
    mapping = {
        "memory": "memory",
        "preference": "memory",
        "meeting_note": "meeting_note",
        "daily_log": "daily_log",
        "question": "question",
        "commitment": "commitment",
        "reminder": "reminder",
        "goal": "goal",
        "habit": "habit",
        "routine": "routine",
        "task": "task",
        "idea": "idea",
        "correction": "idea",
    }
    return mapping.get(item.user_intent, "idea")


def _legacy_destination_from_plan(item: CapturePlanItemResponse) -> str:
    if item.destination == "context_event":
        return "meeting_context"
    if item.destination == "no_action":
        return "needs_answer"
    return item.destination


def plan_items_to_capture_items(plan: CapturePlanDocumentResponse) -> list[CaptureItemResponse]:
    return [
        CaptureItemResponse(
            type=_capture_item_type_from_plan(item),
            domain=item.domain,
            title=item.title,
            summary=item.summary,
            source_span=item.source_span,
            confidence=item.confidence,
            due_at=item.due_at,
            recurrence=item.recurrence,
            needs_follow_up=item.needs_clarification,
            follow_up_questions=list(item.questions),
            suggested_destination=_legacy_destination_from_plan(item),
        )
        for item in plan.items
    ]


async def split_capture_message(
    *,
    message: str,
    timezone_name: str | None,
    route_hint: str | None = None,
) -> tuple[list[CaptureItemResponse], list[str]]:
    _, critic = await plan_capture_text(message=message, timezone_name=timezone_name, route_hint=route_hint)
    return plan_items_to_capture_items(critic.final_plan), list(critic.final_plan.uncaptured_residue)


async def _create_capture_plan_row(
    *,
    raw_capture: RawCapture,
    planner_plan: CapturePlanDocumentResponse,
    critic: CapturePlanCriticResponse,
) -> CapturePlan:
    async with async_session() as db:
        row = CapturePlan(
            raw_capture_id=raw_capture.id,
            planner_model=PLANNER_MODEL,
            critic_model=CRITIC_MODEL,
            plan_json=planner_plan.model_dump(mode="json"),
            critic_json=critic.model_dump(mode="json"),
            final_plan_json=critic.final_plan.model_dump(mode="json"),
            confidence=critic.final_plan.overall_confidence,
            status="critic_approved" if critic.approved else "critic_revised",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def _replace_capture_plan_items(
    capture_plan_id: int,
    items: list[CapturePlanItemResponse],
    *,
    existing_rows: list[CaptureItemPlan] | None = None,
) -> list[CaptureItemPlan]:
    async with async_session() as db:
        if existing_rows is None:
            result = await db.execute(
                select(CaptureItemPlan).where(CaptureItemPlan.capture_plan_id == capture_plan_id).order_by(CaptureItemPlan.id.asc())
            )
            existing_rows = list(result.scalars().all())
        else:
            requested_ids = [row.id for row in existing_rows if getattr(row, "id", None)]
            persistent_rows: list[CaptureItemPlan] = []
            if requested_ids:
                result = await db.execute(
                    select(CaptureItemPlan).where(CaptureItemPlan.id.in_(requested_ids)).order_by(CaptureItemPlan.id.asc())
                )
                persistent_rows = list(result.scalars().all())
            persistent_by_id = {row.id: row for row in persistent_rows}
            resolved_rows: list[CaptureItemPlan] = []
            for row in existing_rows:
                row_id = getattr(row, "id", None)
                resolved_rows.append(persistent_by_id.get(row_id, row))
            existing_rows = resolved_rows
        rows_by_id = {row.id: row for row in existing_rows}
        seen_ids: set[int] = set()
        created_or_updated: list[CaptureItemPlan] = []
        for index, item in enumerate(items):
            row = rows_by_id.get(item.id) if item.id else None
            if not row and index < len(existing_rows):
                candidate = existing_rows[index]
                if candidate.id not in seen_ids:
                    row = candidate
            if row:
                seen_ids.add(row.id)
                row.title = item.title
                row.summary = item.summary
                row.user_intent = item.user_intent
                row.destination = item.destination
                row.domain = item.domain
                row.kind = item.kind
                row.due_at = item.due_at
                row.due_expression = item.due_expression
                row.recurrence = item.recurrence
                row.should_schedule_reminder = item.should_schedule_reminder
                row.should_appear_in_focus = item.should_appear_in_focus
                row.needs_clarification = item.needs_clarification
                row.questions_json = item.questions
                row.confidence = item.confidence
                row.reasoning_summary = item.reasoning_summary
                row.source_span = item.source_span
                row.execution_metadata_json = item.execution_metadata
                created_or_updated.append(row)
                continue
            row = CaptureItemPlan(
                capture_plan_id=capture_plan_id,
                title=item.title,
                summary=item.summary,
                user_intent=item.user_intent,
                destination=item.destination,
                domain=item.domain,
                kind=item.kind,
                due_at=item.due_at,
                due_expression=item.due_expression,
                recurrence=item.recurrence,
                should_schedule_reminder=item.should_schedule_reminder,
                should_appear_in_focus=item.should_appear_in_focus,
                needs_clarification=item.needs_clarification,
                questions_json=item.questions,
                confidence=item.confidence,
                reasoning_summary=item.reasoning_summary,
                source_span=item.source_span,
                execution_status=item.execution_status or "planned",
                linked_entity_type=item.linked_entity_type,
                linked_entity_id=item.linked_entity_id,
                execution_metadata_json=item.execution_metadata,
            )
            db.add(row)
            created_or_updated.append(row)
        for row in existing_rows:
            if row.id not in seen_ids and row.id in rows_by_id:
                row.execution_status = "replaced"
        await db.commit()
        for row in created_or_updated:
            await db.refresh(row)
        return created_or_updated


def _priority_from_plan(item: CapturePlanItemResponse) -> tuple[str, int, str]:
    score = 45
    signals: list[str] = []
    if item.should_appear_in_focus:
        score = max(score, 80)
        signals.append("planner_focus")
    if item.should_schedule_reminder:
        score = max(score, 72)
        signals.append("schedule_reminder")
    due_at = item.due_at
    if due_at:
        due_utc = due_at.astimezone(timezone.utc) if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        if due_utc <= now_utc + timedelta(hours=24):
            score = max(score, 86)
            signals.append("due_24h")
        elif due_utc <= now_utc + timedelta(days=3):
            score = max(score, 76)
            signals.append("due_3d")
        else:
            score = max(score, 62)
            signals.append("due_future")
    if item.user_intent in {"habit", "routine", "goal"} and item.should_appear_in_focus:
        score = max(score, 78)
        signals.append("planned_anchor")
    if item.domain in {"deen", "family", "health"} and item.should_appear_in_focus:
        score = min(100, score + 4)
        signals.append(f"domain:{item.domain}")
    priority = "high" if score >= 75 else "medium" if score >= 45 else "low"
    return priority, score, f"AI plan: {', '.join(signals) if signals else 'captured item'}."


def _life_item_kind(item: CapturePlanItemResponse) -> str:
    if item.kind in {"goal", "habit", "routine", "task"}:
        return item.kind
    if item.user_intent in {"goal", "habit", "routine"}:
        return item.user_intent
    return "task"


def _life_item_notes(item: CapturePlanItemResponse, *, raw_capture_id: int, capture_plan_id: int) -> str:
    parts = [
        f"Summary: {item.summary}",
        f"Why: {item.reasoning_summary}" if item.reasoning_summary else "",
        f"Source span: {item.source_span}",
        f"Raw capture: lifeos://raw-capture/{raw_capture_id}",
        f"Capture plan: lifeos://capture-plan/{capture_plan_id}",
    ]
    if item.recurrence:
        parts.append(f"Recurrence: {item.recurrence}")
    return "\n\n".join(part for part in parts if part)


def _plan_context_links(*, raw_capture_id: int, capture_plan_id: int, capture_item_plan_id: int) -> list[dict[str, Any]]:
    return [
        {"type": "raw_capture", "id": raw_capture_id},
        {"type": "capture_plan", "id": capture_plan_id},
        {"type": "capture_item_plan", "id": capture_item_plan_id},
    ]


async def _create_intake_entry_for_plan(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    status: str,
) -> IntakeEntry:
    async with async_session() as db:
        entry = IntakeEntry(
            source=raw_capture.source,
            source_agent="capture-planner",
            source_session_id=raw_capture.session_id,
            raw_text=item_row.source_span,
            title=item_row.title,
            summary=item_row.summary,
            domain=item_row.domain,
            kind=item_row.kind or "idea",
            status=status,
            desired_outcome=item_row.summary,
            next_action=item_row.title,
            follow_up_questions_json=list(item_row.questions_json or []),
            structured_data_json={
                "raw_capture_id": raw_capture.id,
                "capture_plan_id": capture_plan_row.id,
                "capture_item_plan_id": item_row.id,
                "user_intent": item_row.user_intent,
                "destination": item_row.destination,
            },
            promotion_payload_json=None,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry


async def _update_intake_entry_status(entry_id: int, *, status: str, follow_up_questions: list[str] | None = None, linked_life_item_id: int | None = None) -> IntakeEntry | None:
    payload = {
        "status": status,
        "follow_up_questions": follow_up_questions,
    }
    async with async_session() as db:
        row = await db.get(IntakeEntry, entry_id)
        if not row:
            return None
        row.status = status
        if follow_up_questions is not None:
            row.follow_up_questions_json = follow_up_questions
        if linked_life_item_id is not None:
            row.linked_life_item_id = linked_life_item_id
        await db.commit()
        await db.refresh(row)
        return row


async def _archive_memory_proposals(proposal_ids: list[int]) -> None:
    if not proposal_ids:
        return
    async with async_session() as db:
        result = await db.execute(select(SharedMemoryProposal).where(SharedMemoryProposal.id.in_(proposal_ids)))
        for row in result.scalars().all():
            row.status = "rejected"
        await db.commit()


async def _archive_context_events(event_ids: list[int]) -> None:
    if not event_ids:
        return
    async with async_session() as db:
        result = await db.execute(select(ContextEvent).where(ContextEvent.id.in_(event_ids)))
        for row in result.scalars().all():
            row.status = "archived"
        await db.commit()


async def _archive_item_side_effects(item_row: CaptureItemPlan) -> None:
    metadata = dict(item_row.execution_metadata_json or {})
    intake_entry_id = metadata.get("intake_entry_id")
    if intake_entry_id:
        await _update_intake_entry_status(int(intake_entry_id), status="archived", follow_up_questions=[])
    if item_row.linked_entity_type == "life_item" and item_row.linked_entity_id:
        await update_life_item(int(item_row.linked_entity_id), LifeItemUpdate(status="archived", focus_eligible=False))
    if item_row.linked_entity_type == "shared_memory_proposal":
        proposal_ids = metadata.get("proposal_ids") or ([item_row.linked_entity_id] if item_row.linked_entity_id else [])
        await _archive_memory_proposals([int(value) for value in proposal_ids if value])
    if item_row.linked_entity_type == "context_event":
        event_ids = metadata.get("event_ids") or ([item_row.linked_entity_id] if item_row.linked_entity_id else [])
        await _archive_context_events([int(value) for value in event_ids if value])
        proposal_ids = metadata.get("proposal_ids") or []
        await _archive_memory_proposals([int(value) for value in proposal_ids if value])
    follow_up_job_id = metadata.get("follow_up_job_id")
    if item_row.linked_entity_type == "life_item" and item_row.linked_entity_id and follow_up_job_id:
        await disable_follow_up_job(int(item_row.linked_entity_id), reason="capture_correction")


async def _execute_life_item(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    item: CapturePlanItemResponse,
) -> CaptureRoutedResultResponse:
    if item.should_schedule_reminder and item.due_at is None:
        entry = await _create_intake_entry_for_plan(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, status="clarifying")
        item_row.execution_status = "needs_answer"
        item_row.linked_entity_type = "intake_entry"
        item_row.linked_entity_id = entry.id
        item_row.execution_metadata_json = {"intake_entry_id": entry.id}
        return CaptureRoutedResultResponse(
            capture_item_plan_id=item_row.id,
            item_index=0,
            type=_capture_item_type_from_plan(item),
            title=item.title,
            destination="needs_answer",
            status="needs_answer",
            message="Reminder needs due time before LifeOS can schedule it.",
            entry=IntakeEntryResponse.model_validate(entry),
            follow_up_questions=item.questions or ["What due time should LifeOS use for this reminder?"],
        )
    priority, score, reason = _priority_from_plan(item)
    entry = await _create_intake_entry_for_plan(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, status="processed")
    life_item = await create_life_item(
        LifeItemCreate(
            domain=item.domain,
            title=item.title,
            kind=_life_item_kind(item),
            notes=_life_item_notes(item, raw_capture_id=raw_capture.id, capture_plan_id=capture_plan_row.id),
            priority=priority,
            due_at=item.due_at,
            recurrence_rule=item.recurrence,
            source_agent="capture-planner",
            risk_level="low",
            focus_eligible=item.should_appear_in_focus,
            priority_score=score,
            priority_reason=reason,
            context_links=_plan_context_links(
                raw_capture_id=raw_capture.id,
                capture_plan_id=capture_plan_row.id,
                capture_item_plan_id=item_row.id,
            ),
            last_prioritized_at=datetime.now(timezone.utc),
        )
    )
    await _update_intake_entry_status(entry.id, status="processed", follow_up_questions=[], linked_life_item_id=life_item.id)
    follow_up_job = None
    if item.should_schedule_reminder:
        follow_up_job = await upsert_follow_up_job(life_item.id, reminder_at=item.due_at)
    item_row.execution_status = "tracked"
    item_row.linked_entity_type = "life_item"
    item_row.linked_entity_id = life_item.id
    item_row.execution_metadata_json = {
        "intake_entry_id": entry.id,
        "follow_up_job_id": follow_up_job.id if follow_up_job else None,
    }
    return CaptureRoutedResultResponse(
        capture_item_plan_id=item_row.id,
        item_index=0,
        type=_capture_item_type_from_plan(item),
        title=item.title,
        destination="life_item",
        status="tracked",
        message="Tracked as life item." if not follow_up_job else "Tracked as life item and scheduled reminder.",
        entry=IntakeEntryResponse.model_validate(entry),
        life_item=LifeItemResponse.model_validate(life_item),
        follow_up_job=ScheduledJobResponse.model_validate(follow_up_job) if follow_up_job else None,
        metadata={"tool_calls": ["create_life_item"] + (["schedule_follow_up"] if follow_up_job else [])},
    )


async def _execute_memory_review(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    item: CapturePlanItemResponse,
) -> CaptureRoutedResultResponse:
    proposal = await create_shared_memory_review_proposal(
        SharedMemoryPromoteRequest(
            agent_name="wiki-curator",
            title=item.title,
            content=(
                f"## Summary\n{item.summary}\n\n"
                f"## Why\n{item.reasoning_summary or 'Captured by planner.'}\n\n"
                f"## Source Span\n{item.source_span}\n\n"
                f"## Raw Capture\nlifeos://raw-capture/{raw_capture.id}\n"
            ),
            scope="shared_domain",
            domain=item.domain,
            session_id=raw_capture.session_id,
            source_uri=f"lifeos://raw-capture/{raw_capture.id}",
            tags=["lifeos", "capture-planner", item.user_intent],
            confidence="high" if item.confidence >= 0.8 else "medium",
        )
    )
    item_row.execution_status = "queued_for_review"
    item_row.linked_entity_type = "shared_memory_proposal"
    item_row.linked_entity_id = proposal.id
    item_row.execution_metadata_json = {"proposal_ids": [proposal.id]}
    return CaptureRoutedResultResponse(
        capture_item_plan_id=item_row.id,
        item_index=0,
        type=_capture_item_type_from_plan(item),
        title=item.title,
        destination="memory_review",
        status="queued_for_review",
        message="Queued memory review.",
        wiki_proposals=[SharedMemoryProposalResponse.model_validate(proposal)],
        metadata={"tool_calls": ["create_memory_review_proposal"]},
    )


async def _execute_context_event(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    item: CapturePlanItemResponse,
) -> CaptureRoutedResultResponse:
    event, proposals, intake_entry_ids = await capture_meeting_summary(
        MeetingIntakeRequest(
            summary=item.source_span,
            title=item.title,
            domain=item.domain,
            source=raw_capture.source,
            source_agent="capture-planner",
            session_id=raw_capture.session_id,
            tags=["capture-planner", f"raw-capture:{raw_capture.id}", f"capture-plan:{capture_plan_row.id}"],
        )
    )
    item_row.execution_status = "queued_for_review"
    item_row.linked_entity_type = "context_event"
    item_row.linked_entity_id = event.id
    item_row.execution_metadata_json = {
        "event_ids": [event.id],
        "proposal_ids": [proposal.id for proposal in proposals],
        "intake_entry_ids": intake_entry_ids,
    }
    return CaptureRoutedResultResponse(
        capture_item_plan_id=item_row.id,
        item_index=0,
        type=_capture_item_type_from_plan(item),
        title=item.title,
        destination="context_event",
        status="queued_for_review",
        message="Created context event and queued memory review.",
        event=ContextEventResponse.model_validate(event),
        wiki_proposals=[SharedMemoryProposalResponse.model_validate(proposal) for proposal in proposals],
        metadata={"tool_calls": ["create_context_event", "create_memory_review_proposal"], "intake_entry_ids": intake_entry_ids},
    )


def _sleep_payload(text: str) -> DailyLogCreate | None:
    match = SLEEP_HOURS_RE.search(text or "")
    if not match:
        return None
    bedtime = BEDTIME_RE.search(text or "")
    wake = WAKE_RE.search(text or "")
    return DailyLogCreate(
        kind="sleep",
        hours=float(match.group(1)),
        bedtime=bedtime.group(1).zfill(5) if bedtime else None,
        wake_time=wake.group(1).zfill(5) if wake else None,
        note=(text or "").strip()[:500] or None,
    )


def _training_payload(text: str) -> DailyLogCreate | None:
    lowered = str(text or "").lower()
    if TRAINING_REST_RE.search(lowered):
        return DailyLogCreate(kind="training", status="rest", note=(text or "").strip()[:500] or None)
    if TRAINING_MISSED_RE.search(lowered):
        return DailyLogCreate(kind="training", status="missed", note=(text or "").strip()[:500] or None)
    if TRAINING_DONE_RE.search(lowered):
        return DailyLogCreate(kind="training", status="done", note=(text or "").strip()[:500] or None)
    return None


async def _prayer_payload_result(text: str) -> dict[str, Any] | None:
    prayer = PRAYER_NAME_RE.search(text or "")
    if not prayer:
        return None
    if PRAYER_MISSED_RE.search(text or ""):
        status = "missed"
    elif PRAYER_LATE_RE.search(text or ""):
        status = "late"
    else:
        status = "on_time"
    schedule = await get_today_schedule()
    return await log_prayer_checkin_retroactive(
        PrayerRetroactiveCheckinRequest(
            prayer_date=str(schedule.get("date")),
            prayer_name=prayer.group(1).title(),
            status=status,
            note=(text or "").strip()[:500] or None,
            source="capture-planner",
        )
    )


async def _execute_daily_log(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    item: CapturePlanItemResponse,
) -> CaptureRoutedResultResponse:
    text = item.source_span or item.summary or item.title
    logged_signals: list[str] = []
    messages: list[str] = []
    if item.kind in {"meal", "meal_log"} or (item.kind == "daily_log" and MEAL_RE.search(text)):
        result = await log_daily_signal(DailyLogCreate(kind="meal", count=1, note=text[:500] or None))
        logged_signals.append("meal")
        messages.append(result["message"])
    if item.kind in {"hydration", "water"} or (item.kind == "daily_log" and WATER_RE.search(text)):
        count_match = WATER_COUNT_RE.search(text or "")
        count = max(1, min(12, int(count_match.group(1)))) if count_match else 1
        result = await log_daily_signal(DailyLogCreate(kind="hydration", count=count, note=text[:500] or None))
        logged_signals.append(f"hydration x{count}")
        messages.append(result["message"])
    sleep = _sleep_payload(text) if item.kind in {"sleep", "sleep_log", "daily_log"} else None
    if sleep:
        result = await log_daily_signal(sleep)
        logged_signals.append("sleep")
        messages.append(result["message"])
    training = _training_payload(text) if item.kind in {"training", "training_log", "daily_log"} else None
    if training:
        result = await log_daily_signal(training)
        logged_signals.append(f"training:{training.status}")
        messages.append(result["message"])
    prayer = await _prayer_payload_result(text) if item.kind in {"prayer", "prayer_checkin", "daily_log"} else None
    if prayer:
        logged_signals.append(f"prayer:{prayer['prayer_name'].lower()}:{prayer['status_raw']}")
        messages.append(f"Logged prayer check-in for {prayer['prayer_name']}.")
    if not logged_signals:
        entry = await _create_intake_entry_for_plan(
            raw_capture=raw_capture,
            capture_plan_row=capture_plan_row,
            item_row=item_row,
            status="clarifying",
        )
        item_row.execution_status = "needs_answer"
        item_row.linked_entity_type = "intake_entry"
        item_row.linked_entity_id = entry.id
        item_row.execution_metadata_json = {"intake_entry_id": entry.id}
        return CaptureRoutedResultResponse(
            capture_item_plan_id=item_row.id,
            item_index=0,
            type="daily_log",
            title=item.title,
            destination="needs_answer",
            status="needs_answer",
            message="Daily log needs more structure before execution.",
            entry=IntakeEntryResponse.model_validate(entry),
            follow_up_questions=item.questions or ["What exact daily log should LifeOS apply here?"],
        )
    item_row.execution_status = "logged"
    item_row.linked_entity_type = "daily_log"
    item_row.execution_metadata_json = {"logged_signals": logged_signals, "messages": messages}
    return CaptureRoutedResultResponse(
        capture_item_plan_id=item_row.id,
        item_index=0,
        type="daily_log",
        title=item.title,
        destination="daily_log",
        status="logged",
        message=" ".join(messages)[:1000] or "Logged daily status.",
        logged_signals=logged_signals,
        metadata={"tool_calls": ["log_daily_signal"]},
    )


async def _execute_needs_answer(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    item: CapturePlanItemResponse,
) -> CaptureRoutedResultResponse:
    entry = await _create_intake_entry_for_plan(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, status="clarifying")
    item_row.execution_status = "needs_answer"
    item_row.linked_entity_type = "intake_entry"
    item_row.linked_entity_id = entry.id
    item_row.execution_metadata_json = {"intake_entry_id": entry.id}
    return CaptureRoutedResultResponse(
        capture_item_plan_id=item_row.id,
        item_index=0,
        type=_capture_item_type_from_plan(item),
        title=item.title,
        destination="needs_answer",
        status="needs_answer",
        message="Needs answer before safe execution.",
        entry=IntakeEntryResponse.model_validate(entry),
        follow_up_questions=item.questions or ["What should LifeOS do with this item?"],
        metadata={"tool_calls": ["create_intake_entry"]},
    )


async def _execute_no_action(item_row: CaptureItemPlan, item: CapturePlanItemResponse) -> CaptureRoutedResultResponse:
    item_row.execution_status = "no_action"
    item_row.linked_entity_type = None
    item_row.linked_entity_id = None
    item_row.execution_metadata_json = {"tool_calls": []}
    return CaptureRoutedResultResponse(
        capture_item_plan_id=item_row.id,
        item_index=0,
        type=_capture_item_type_from_plan(item),
        title=item.title,
        destination="no_action",
        status="no_action",
        message="Stored in audit only. No action executed.",
        metadata={"tool_calls": []},
    )


async def _execute_item(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    item: CapturePlanItemResponse,
    timezone_name: str | None,
) -> CaptureRoutedResultResponse:
    normalized_due = await normalize_due_expression(
        item.due_expression,
        provided_due_at=item.due_at,
        timezone_name=timezone_name,
    )
    if normalized_due is not None:
        item.due_at = normalized_due
        item_row.due_at = normalized_due
    should_hold = (
        item.needs_clarification
        or item.confidence < 0.55
        or (item.destination == "life_item" and item.user_intent in {"question", "idea"} and item.kind not in {"task", "goal", "habit", "routine"})
    )
    if should_hold and item.destination != "no_action":
        item.destination = "needs_answer"
        item_row.destination = "needs_answer"
    if item.destination == "life_item":
        return await _execute_life_item(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, item=item)
    if item.destination == "memory_review":
        return await _execute_memory_review(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, item=item)
    if item.destination == "context_event":
        return await _execute_context_event(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, item=item)
    if item.destination == "daily_log":
        return await _execute_daily_log(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, item=item)
    if item.destination == "no_action":
        return await _execute_no_action(item_row, item)
    return await _execute_needs_answer(raw_capture=raw_capture, capture_plan_row=capture_plan_row, item_row=item_row, item=item)


async def _persist_item_row(item_row: CaptureItemPlan) -> CaptureItemPlan:
    async with async_session() as db:
        row = await db.get(CaptureItemPlan, item_row.id)
        if not row:
            return item_row
        row.destination = item_row.destination
        row.due_at = item_row.due_at
        row.due_expression = item_row.due_expression
        row.execution_status = item_row.execution_status
        row.linked_entity_type = item_row.linked_entity_type
        row.linked_entity_id = item_row.linked_entity_id
        row.execution_metadata_json = item_row.execution_metadata_json
        row.title = item_row.title
        row.summary = item_row.summary
        row.user_intent = item_row.user_intent
        row.domain = item_row.domain
        row.kind = item_row.kind
        row.recurrence = item_row.recurrence
        row.should_schedule_reminder = item_row.should_schedule_reminder
        row.should_appear_in_focus = item_row.should_appear_in_focus
        row.needs_clarification = item_row.needs_clarification
        row.questions_json = list(getattr(item_row, "questions_json", None) or [])
        row.confidence = item_row.confidence
        row.reasoning_summary = item_row.reasoning_summary
        row.source_span = item_row.source_span
        await db.commit()
        await db.refresh(row)
        return row


async def execute_capture_plan(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    plan: CapturePlanDocumentResponse,
    timezone_name: str | None,
) -> tuple[
    list[CaptureRoutedResultResponse],
    list[IntakeEntryResponse],
    list[LifeItemResponse],
    list[SharedMemoryProposalResponse],
    ScheduledJobResponse | None,
    ContextEventResponse | None,
    list[str],
    list[LifeItemResponse],
]:
    item_rows = await _replace_capture_plan_items(capture_plan_row.id, plan.items)
    routed_results: list[CaptureRoutedResultResponse] = []
    entries: list[IntakeEntryResponse] = []
    life_items: list[LifeItemResponse] = []
    wiki_proposals: list[SharedMemoryProposalResponse] = []
    first_follow_up_job: ScheduledJobResponse | None = None
    first_event: ContextEventResponse | None = None
    logged_signals: list[str] = []
    completed_items: list[LifeItemResponse] = []
    for index, item_row in enumerate(item_rows):
        item = plan.items[index]
        item.id = item_row.id
        routed = await _execute_item(
            raw_capture=raw_capture,
            capture_plan_row=capture_plan_row,
            item_row=item_row,
            item=item,
            timezone_name=timezone_name,
        )
        routed.item_index = index
        await _persist_item_row(item_row)
        routed_results.append(routed)
        if routed.entry:
            entries.append(routed.entry)
        if routed.life_item:
            life_items.append(routed.life_item)
        if routed.wiki_proposals:
            wiki_proposals.extend(routed.wiki_proposals)
        if routed.follow_up_job and first_follow_up_job is None:
            first_follow_up_job = routed.follow_up_job
        if routed.event and first_event is None:
            first_event = routed.event
        for signal in routed.logged_signals or []:
            if signal not in logged_signals:
                logged_signals.append(signal)
        for row in routed.completed_items or []:
            if row.id not in {item.id for item in completed_items}:
                completed_items.append(row)
    return (
        routed_results,
        entries,
        life_items,
        wiki_proposals,
        first_follow_up_job,
        first_event,
        logged_signals,
        completed_items,
    )


async def _load_latest_capture_plan(session_id: int) -> tuple[RawCapture, CapturePlan, list[CaptureItemPlan]] | None:
    async with async_session() as db:
        result = await db.execute(
            select(CapturePlan, RawCapture)
            .join(RawCapture, RawCapture.id == CapturePlan.raw_capture_id)
            .where(RawCapture.session_id == session_id)
            .order_by(CapturePlan.updated_at.desc(), CapturePlan.id.desc())
        )
        row = result.first()
        if not row:
            return None
        plan_row, raw_capture = row
        items_result = await db.execute(
            select(CaptureItemPlan).where(CaptureItemPlan.capture_plan_id == plan_row.id).order_by(CaptureItemPlan.id.asc())
        )
        return raw_capture, plan_row, list(items_result.scalars().all())


def _current_questions_text(item_rows: list[CaptureItemPlan]) -> str:
    questions: list[str] = []
    for row in item_rows:
        for question in list(row.questions_json or []):
            cleaned = _clean_text(question, limit=240)
            if cleaned and cleaned not in questions:
                questions.append(cleaned)
    if not questions:
        return "No clarification needed."
    return "Open questions:\n" + "\n".join(f"- {question}" for question in questions[:6])


def _correction_prompt(
    *,
    original_message: str,
    current_plan: CapturePlanDocumentResponse,
    current_items: list[CaptureItemPlan],
    user_message: str,
    timezone_name: str,
    examples: list[CaptureCorrection],
) -> str:
    current_items_payload = []
    for index, item in enumerate(current_plan.items):
        current_items_payload.append(
            {
                "id": current_items[index].id if index < len(current_items) else item.id,
                **item.model_dump(mode="json"),
                "execution_status": current_items[index].execution_status if index < len(current_items) else item.execution_status,
                "linked_entity_type": current_items[index].linked_entity_type if index < len(current_items) else item.linked_entity_type,
                "linked_entity_id": current_items[index].linked_entity_id if index < len(current_items) else item.linked_entity_id,
            }
        )
    return (
        "You are LifeOS Capture Correction Agent.\n"
        "User replying to latest capture plan.\n"
        "Return JSON only.\n"
        "Schema:\n"
        "{"
        "\"mode\":\"correction|clarify|new_capture\","
        "\"target_item_ids\":[1],"
        "\"clarification_response\":\"... or null\","
        "\"lesson\":\"short reusable lesson\","
        "\"corrected_plan\":{"
        "\"items\":[{"
        "\"id\":1,"
        "\"title\":\"...\","
        "\"summary\":\"...\","
        "\"user_intent\":\"commitment|reminder|memory|preference|task|goal|habit|routine|daily_log|meeting_note|question|idea|correction\","
        "\"destination\":\"life_item|memory_review|daily_log|needs_answer|context_event|no_action\","
        "\"domain\":\"deen|family|work|health|planning\","
        "\"kind\":\"...\","
        "\"due_at\":\"ISO-8601 datetime or null\","
        "\"due_expression\":\"exact due phrase or null\","
        "\"recurrence\":\"string or null\","
        "\"should_schedule_reminder\":false,"
        "\"should_appear_in_focus\":false,"
        "\"needs_clarification\":false,"
        "\"questions\":[],"
        "\"confidence\":0.0,"
        "\"reasoning_summary\":\"...\","
        "\"source_span\":\"exact text span\""
        "}],"
        "\"uncaptured_residue\":[\"...\"],"
        "\"overall_confidence\":0.0,"
        "\"user_visible_summary\":\"...\""
        "} or null"
        "}\n"
        "Rules:\n"
        "- If user asks what is unclear, mode=clarify and answer with open questions.\n"
        "- If user message corrects latest plan, mode=correction and return full corrected plan.\n"
        "- Preserve existing item ids for revised items. Omit id only for truly new split items.\n"
        "- If user says forget/archive, destination=no_action for affected item.\n"
        "- If user says make reminder, set destination=life_item, user_intent=reminder, should_schedule_reminder=true.\n"
        "- If user says do not put in focus, set should_appear_in_focus=false.\n"
        "- If user says memory not task, destination=memory_review and user_intent=memory or preference.\n"
        "- If user reply unrelated to latest capture, mode=new_capture.\n"
        f"Local timezone: {timezone_name}.\n"
        "Relevant prior correction lessons:\n"
        f"{_correction_examples_text(examples)}\n"
        f"Original capture:\n{original_message}\n\n"
        f"Current plan:\n{json.dumps({'items': current_items_payload, 'uncaptured_residue': current_plan.uncaptured_residue, 'overall_confidence': current_plan.overall_confidence, 'user_visible_summary': current_plan.user_visible_summary}, ensure_ascii=True)}\n\n"
        f"User reply:\n{user_message}"
    )


async def _correction_agent_review(
    *,
    original_message: str,
    current_plan: CapturePlanDocumentResponse,
    current_items: list[CaptureItemPlan],
    user_message: str,
    timezone_name: str,
    examples: list[CaptureCorrection],
) -> dict[str, Any]:
    raw = await chat_completion(
        messages=[
            {"role": "system", "content": "Return strict JSON only."},
            {
                "role": "user",
                "content": _correction_prompt(
                    original_message=original_message,
                    current_plan=current_plan,
                    current_items=current_items,
                    user_message=user_message,
                    timezone_name=timezone_name,
                    examples=examples,
                ),
            },
        ],
        provider=CORRECTION_PROVIDER,
        model=CORRECTION_MODEL,
        fallback_provider=CORRECTION_FALLBACK_PROVIDER,
        fallback_model=CORRECTION_FALLBACK_MODEL,
        temperature=0.0,
        max_tokens=2200,
    )
    return _extract_json(str(raw or "")) or {}


async def _apply_corrected_item(
    *,
    raw_capture: RawCapture,
    capture_plan_row: CapturePlan,
    item_row: CaptureItemPlan,
    new_item: CapturePlanItemResponse,
    timezone_name: str | None,
) -> CaptureRoutedResultResponse:
    old_destination = item_row.destination
    item_row.title = new_item.title
    item_row.summary = new_item.summary
    item_row.user_intent = new_item.user_intent
    item_row.destination = new_item.destination
    item_row.domain = new_item.domain
    item_row.kind = new_item.kind
    item_row.due_at = new_item.due_at
    item_row.due_expression = new_item.due_expression
    item_row.recurrence = new_item.recurrence
    item_row.should_schedule_reminder = new_item.should_schedule_reminder
    item_row.should_appear_in_focus = new_item.should_appear_in_focus
    item_row.needs_clarification = new_item.needs_clarification
    item_row.questions_json = new_item.questions
    item_row.confidence = new_item.confidence
    item_row.reasoning_summary = new_item.reasoning_summary
    item_row.source_span = new_item.source_span
    if old_destination != new_item.destination:
        await _archive_item_side_effects(item_row)
        item_row.linked_entity_type = None
        item_row.linked_entity_id = None
        item_row.execution_metadata_json = None
    elif old_destination == "life_item" and item_row.linked_entity_type == "life_item" and item_row.linked_entity_id:
        priority, score, reason = _priority_from_plan(new_item)
        existing = await update_life_item(
            int(item_row.linked_entity_id),
            LifeItemUpdate(
                domain=new_item.domain,
                kind=_life_item_kind(new_item),
                title=new_item.title,
                notes=_life_item_notes(new_item, raw_capture_id=raw_capture.id, capture_plan_id=capture_plan_row.id),
                priority=priority,
                due_at=new_item.due_at,
                recurrence_rule=new_item.recurrence,
                focus_eligible=new_item.should_appear_in_focus,
                priority_score=score,
                priority_reason=reason,
                context_links=_plan_context_links(
                    raw_capture_id=raw_capture.id,
                    capture_plan_id=capture_plan_row.id,
                    capture_item_plan_id=item_row.id,
                ),
                last_prioritized_at=datetime.now(timezone.utc),
                status="open",
            ),
        )
        follow_up_job = None
        if existing and new_item.should_schedule_reminder:
            follow_up_job = await upsert_follow_up_job(existing.id, reminder_at=new_item.due_at)
        elif existing and item_row.execution_metadata_json and item_row.execution_metadata_json.get("follow_up_job_id"):
            await disable_follow_up_job(existing.id, reason="capture_correction")
        entry_id = (item_row.execution_metadata_json or {}).get("intake_entry_id")
        updated_entry = None
        if entry_id:
            updated_entry = await _update_intake_entry_status(
                int(entry_id),
                status="processed",
                follow_up_questions=[],
                linked_life_item_id=existing.id if existing else None,
            )
        item_row.execution_status = "updated"
        item_row.execution_metadata_json = {
            "intake_entry_id": entry_id,
            "follow_up_job_id": follow_up_job.id if follow_up_job else None,
        }
        return CaptureRoutedResultResponse(
            capture_item_plan_id=item_row.id,
            item_index=0,
            type=_capture_item_type_from_plan(new_item),
            title=new_item.title,
            destination="life_item",
            status="updated",
            message="Updated tracked life item.",
            entry=IntakeEntryResponse.model_validate(updated_entry) if updated_entry else None,
            life_item=LifeItemResponse.model_validate(existing) if existing else None,
            follow_up_job=ScheduledJobResponse.model_validate(follow_up_job) if follow_up_job else None,
            metadata={"tool_calls": ["update_life_item"] + (["schedule_follow_up"] if follow_up_job else [])},
        )
    elif old_destination == "memory_review" and item_row.linked_entity_type == "shared_memory_proposal" and item_row.linked_entity_id:
        async with async_session() as db:
            proposal = await db.get(SharedMemoryProposal, int(item_row.linked_entity_id))
            if proposal:
                proposal.title = new_item.title
                proposal.domain = new_item.domain
                proposal.proposed_content = (
                    f"## Summary\n{new_item.summary}\n\n"
                    f"## Why\n{new_item.reasoning_summary or 'Captured by planner.'}\n\n"
                    f"## Source Span\n{new_item.source_span}\n\n"
                    f"## Raw Capture\nlifeos://raw-capture/{raw_capture.id}\n"
                )
                await db.commit()
                await db.refresh(proposal)
                item_row.execution_status = "updated"
                item_row.execution_metadata_json = {"proposal_ids": [proposal.id]}
                return CaptureRoutedResultResponse(
                    capture_item_plan_id=item_row.id,
                    item_index=0,
                    type=_capture_item_type_from_plan(new_item),
                    title=new_item.title,
                    destination="memory_review",
                    status="updated",
                    message="Updated memory review proposal.",
                    wiki_proposals=[SharedMemoryProposalResponse.model_validate(proposal)],
                    metadata={"tool_calls": ["update_memory_review_proposal"]},
                )
    elif old_destination == "context_event" and item_row.linked_entity_type == "context_event" and item_row.linked_entity_id:
        async with async_session() as db:
            event = await db.get(ContextEvent, int(item_row.linked_entity_id))
            if event:
                event.title = new_item.title
                event.summary = new_item.summary
                event.raw_text = new_item.source_span
                event.domain = new_item.domain
                await db.commit()
                await db.refresh(event)
                item_row.execution_status = "updated"
                return CaptureRoutedResultResponse(
                    capture_item_plan_id=item_row.id,
                    item_index=0,
                    type=_capture_item_type_from_plan(new_item),
                    title=new_item.title,
                    destination="context_event",
                    status="updated",
                    message="Updated context event.",
                    event=ContextEventResponse.model_validate(event),
                    metadata={"tool_calls": ["update_context_event"]},
                )
    return await _execute_item(
        raw_capture=raw_capture,
        capture_plan_row=capture_plan_row,
        item_row=item_row,
        item=new_item,
        timezone_name=timezone_name,
    )


async def continue_capture_session(
    *,
    message: str,
    source: str,
    session_id: int,
    source_message_id: str | None,
    source_channel_id: str | None,
    timezone_name: str | None,
) -> CaptureExecutionBundle | None:
    latest = await _load_latest_capture_plan(session_id)
    if not latest:
        return None
    original_raw_capture, capture_plan_row, current_items = latest
    current_plan = CapturePlanDocumentResponse.model_validate(capture_plan_row.final_plan_json or {})
    correction_raw_capture = await create_raw_capture(
        message=message,
        source=source,
        session_id=session_id,
        source_message_id=source_message_id,
        source_channel_id=source_channel_id,
        status="received",
        metadata={"mode": "capture_followup", "original_raw_capture_id": original_raw_capture.id, "capture_plan_id": capture_plan_row.id},
    )
    examples = await _list_relevant_corrections(message)
    timezone_name = await get_commitment_timezone(timezone_name)
    review = await _correction_agent_review(
        original_message=original_raw_capture.raw_text,
        current_plan=current_plan,
        current_items=current_items,
        user_message=message,
        timezone_name=timezone_name,
        examples=examples,
    )
    mode = _clean_text(review.get("mode"), limit=20).lower() if review.get("mode") else "new_capture"
    if mode == "new_capture":
        return None
    if mode == "clarify" and not isinstance(review.get("corrected_plan"), dict):
        audit_summary = _clean_text(review.get("clarification_response"), limit=600) or _current_questions_text(current_items)
        await update_raw_capture(correction_raw_capture.id, status="clarified", metadata={"audit_summary": audit_summary})
        return CaptureExecutionBundle(
            raw_capture=correction_raw_capture,
            capture_plan_row=capture_plan_row,
            capture_plan=current_plan,
            critic=CapturePlanCriticResponse(approved=True, issues=[], final_plan=current_plan, critic_summary="Clarification only."),
            capture_items=plan_items_to_capture_items(current_plan),
            routed_results=[],
            entries=[],
            life_items=[],
            wiki_proposals=[],
            first_follow_up_job=None,
            first_event=None,
            logged_signals=[],
            completed_items=[],
            corrections=[],
            audit_summary=audit_summary,
            session_id=session_id,
            session_title=None,
        )
    corrected_plan = _normalize_plan_document(review.get("corrected_plan") if isinstance(review.get("corrected_plan"), dict) else None, original_raw_capture.raw_text)
    current_json = current_plan.model_dump(mode="json")
    corrected_json = corrected_plan.model_dump(mode="json")
    target_ids = [int(value) for value in (review.get("target_item_ids") or []) if str(value).isdigit()]
    new_items_by_id = {item.id: item for item in corrected_plan.items if item.id}
    changed_rows: list[CaptureItemPlan] = []
    routed_results: list[CaptureRoutedResultResponse] = []
    for row in current_items:
        if row.id in new_items_by_id:
            changed_rows.append(row)
            routed_results.append(
                await _apply_corrected_item(
                    raw_capture=original_raw_capture,
                    capture_plan_row=capture_plan_row,
                    item_row=row,
                    new_item=new_items_by_id[row.id],
                    timezone_name=timezone_name,
                )
            )
        elif row.id in target_ids:
            no_action = CapturePlanItemResponse(
                id=row.id,
                title=row.title,
                summary=row.summary,
                user_intent=_safe_intent(row.user_intent),
                destination="no_action",
                domain=_safe_domain(row.domain),
                kind=row.kind,
                due_at=row.due_at,
                due_expression=row.due_expression,
                recurrence=row.recurrence,
                should_schedule_reminder=False,
                should_appear_in_focus=False,
                needs_clarification=False,
                questions=[],
                confidence=row.confidence,
                reasoning_summary="Archived by user correction.",
                source_span=row.source_span,
                execution_status="no_action",
                linked_entity_type=None,
                linked_entity_id=None,
                execution_metadata=None,
            )
            routed_results.append(
                await _apply_corrected_item(
                    raw_capture=original_raw_capture,
                    capture_plan_row=capture_plan_row,
                    item_row=row,
                    new_item=no_action,
                    timezone_name=timezone_name,
                )
            )
            changed_rows.append(row)
    existing_ids = {row.id for row in current_items}
    for item in corrected_plan.items:
        if item.id and item.id in existing_ids:
            continue
        created_rows = await _replace_capture_plan_items(capture_plan_row.id, [item], existing_rows=[])
        if created_rows:
            row = created_rows[0]
            item.id = row.id
            routed_results.append(
                await _apply_corrected_item(
                    raw_capture=original_raw_capture,
                    capture_plan_row=capture_plan_row,
                    item_row=row,
                    new_item=item,
                    timezone_name=timezone_name,
                )
            )
            changed_rows.append(row)
    await _replace_capture_plan_items(capture_plan_row.id, corrected_plan.items, existing_rows=current_items + [row for row in changed_rows if row.id not in existing_ids])
    async with async_session() as db:
        row = await db.get(CapturePlan, capture_plan_row.id)
        if row:
            row.final_plan_json = corrected_json
            row.confidence = corrected_plan.overall_confidence
            row.status = "corrected"
            await db.commit()
            await db.refresh(row)
            capture_plan_row = row
    corrections: list[CaptureCorrectionResponse] = []
    correction_lesson = _clean_text(review.get("lesson"), limit=500) or "User correction updated capture plan."
    correction_targets = target_ids or [item.id for item in corrected_plan.items if item.id]
    async with async_session() as db:
        for target_id in correction_targets:
            record = CaptureCorrection(
                raw_capture_id=original_raw_capture.id,
                correction_raw_capture_id=correction_raw_capture.id,
                capture_item_plan_id=target_id,
                user_correction_text=message,
                previous_plan_json=current_json,
                corrected_plan_json=corrected_json,
                lesson=correction_lesson,
            )
            db.add(record)
        await db.commit()
        result = await db.execute(
            select(CaptureCorrection)
            .where(CaptureCorrection.correction_raw_capture_id == correction_raw_capture.id)
            .order_by(CaptureCorrection.id.asc())
        )
        corrections = [CaptureCorrectionResponse.model_validate(row) for row in result.scalars().all()]
    entries: list[IntakeEntryResponse] = [result.entry for result in routed_results if result.entry]
    life_items: list[LifeItemResponse] = [result.life_item for result in routed_results if result.life_item]
    wiki_proposals: list[SharedMemoryProposalResponse] = []
    for result in routed_results:
        wiki_proposals.extend(result.wiki_proposals or [])
    first_follow_up_job = next((result.follow_up_job for result in routed_results if result.follow_up_job), None)
    first_event = next((result.event for result in routed_results if result.event), None)
    logged_signals: list[str] = []
    completed_items: list[LifeItemResponse] = []
    audit_summary = _clean_text(corrected_plan.user_visible_summary, limit=600) or "Applied capture correction."
    await update_raw_capture(correction_raw_capture.id, status="corrected", metadata={"audit_summary": audit_summary, "capture_plan_id": capture_plan_row.id})
    return CaptureExecutionBundle(
        raw_capture=correction_raw_capture,
        capture_plan_row=capture_plan_row,
        capture_plan=corrected_plan,
        critic=CapturePlanCriticResponse(approved=True, issues=[], final_plan=corrected_plan, critic_summary="Correction applied."),
        capture_items=plan_items_to_capture_items(corrected_plan),
        routed_results=routed_results,
        entries=entries,
        life_items=life_items,
        wiki_proposals=wiki_proposals,
        first_follow_up_job=first_follow_up_job,
        first_event=first_event,
        logged_signals=logged_signals,
        completed_items=completed_items,
        corrections=corrections,
        audit_summary=audit_summary,
        session_id=session_id,
        session_title=None,
    )


def _dedupe_by_id(rows: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    deduped: list[Any] = []
    for row in rows:
        row_id = getattr(row, "id", None) if not isinstance(row, dict) else row.get("id")
        marker = (row.__class__.__name__, row_id)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped


async def process_capture_message(
    *,
    message: str,
    source: str,
    session_id: int | None,
    source_message_id: str | None,
    source_channel_id: str | None,
    route_hint: str | None,
    timezone_name: str | None,
) -> CaptureExecutionBundle:
    raw_capture = await create_raw_capture(
        message=message,
        source=source,
        session_id=session_id,
        source_message_id=source_message_id,
        source_channel_id=source_channel_id,
        status="received",
    )
    planner_plan, critic = await plan_capture_text(message=message, timezone_name=timezone_name, route_hint=route_hint)
    capture_plan_row = await _create_capture_plan_row(raw_capture=raw_capture, planner_plan=planner_plan, critic=critic)
    (
        routed_results,
        entries,
        life_items,
        wiki_proposals,
        first_follow_up_job,
        first_event,
        logged_signals,
        completed_items,
    ) = await execute_capture_plan(
        raw_capture=raw_capture,
        capture_plan_row=capture_plan_row,
        plan=critic.final_plan,
        timezone_name=timezone_name,
    )
    entries = _dedupe_by_id(entries)
    life_items = _dedupe_by_id(life_items)
    wiki_proposals = _dedupe_by_id(wiki_proposals)
    completed_items = _dedupe_by_id(completed_items)
    needs_answer_count = sum(1 for result in routed_results if result.destination == "needs_answer" or result.follow_up_questions)
    audit_summary = _clean_text(critic.final_plan.user_visible_summary, limit=600) or f"Captured {len(critic.final_plan.items)} items."
    await update_raw_capture(
        raw_capture.id,
        status="processed",
        metadata={
            "capture_plan_id": capture_plan_row.id,
            "user_visible_summary": critic.final_plan.user_visible_summary,
            "uncaptured_residue": critic.final_plan.uncaptured_residue,
            "needs_answer_count": needs_answer_count,
        },
    )
    return CaptureExecutionBundle(
        raw_capture=raw_capture,
        capture_plan_row=capture_plan_row,
        capture_plan=critic.final_plan,
        critic=critic,
        capture_items=plan_items_to_capture_items(critic.final_plan),
        routed_results=routed_results,
        entries=entries,
        life_items=life_items,
        wiki_proposals=wiki_proposals,
        first_follow_up_job=first_follow_up_job,
        first_event=first_event,
        logged_signals=logged_signals,
        completed_items=completed_items,
        corrections=[],
        audit_summary=audit_summary,
        session_id=session_id,
        session_title=None,
    )
