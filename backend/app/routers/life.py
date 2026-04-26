"""Life items and agenda router."""

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import async_session
from fastapi import APIRouter, Depends, HTTPException, Query

from app.models import (
    CommitmentCaptureRequest,
    CommitmentCaptureResponse,
    DailyFocusCoachResponse,
    DailyLogCreate,
    DailyLogResponse,
    DailyScorecardResponse,
    GoalProgressResponse,
    IntakeEntry,
    IntakeCaptureRequest,
    IntakeCaptureResponse,
    IntakeEntryResponse,
    IntakeEntryUpdate,
    IntakePromoteRequest,
    IntakePromoteResponse,
    LifeCheckinCreate,
    LifeCheckinResponse,
    LifeItemCreate,
    LifeItemResponse,
    LifeItemSnoozeRequest,
    NextPrayerResponse,
    RescuePlanResponse,
    SleepProtocolResponse,
    LifeItemUpdate,
    TodayAgendaResponse,
    UnifiedCaptureRequest,
    UnifiedCaptureResponse,
    WeeklyCommitmentReviewResponse,
    LifeItem,
    ContextEventResponse,
    MeetingIntakeRequest,
    ScheduledJobResponse,
    SharedMemoryProposalResponse,
)
from app.security import require_api_token
from app.services.chat_sessions import create_session, generate_title_from_prompts
from app.services.commitment_coach import get_daily_focus_coach, get_weekly_commitment_review
from app.services.commitments import get_commitment_timezone, upsert_follow_up_job
from app.services.intake import (
    get_intake_entry,
    get_latest_intake_entry_for_session,
    list_intake_entries,
    promote_intake_entry,
    update_intake_entry,
)
from app.services.life_synthesis import synthesize_intake_capture
from app.services.context_events import capture_meeting_summary
from app.services.memory_ledger import record_capture_memory, record_daily_log_memory
from app.services.life import (
    add_checkin,
    create_life_item,
    get_goal_progress,
    get_today_agenda,
    list_life_items,
    log_daily_signal,
    snooze_life_item,
    update_life_item,
)
from app.services.orchestrator import handle_message

router = APIRouter()
COMMITMENT_AGENT_NAME = "commitment-capture"
_CAPTURE_COMMITMENT_RE = re.compile(
    r"\b("
    r"promise|promised|commit|committed|deadline|due|remind me|follow[- ]?up|"
    r"owe|deliver|submit|send|finish|complete|ship|call|pay|invoice|"
    r"today by|tomorrow by|today at|tomorrow at"
    r")\b",
    re.IGNORECASE,
)
_CAPTURE_MEMORY_RE = re.compile(
    r"\b("
    r"meeting|standup|retro|decision|decided|notes?|context|remember that|wiki|"
    r"durable|preference|principle|learned|summary"
    r")\b",
    re.IGNORECASE,
)
_CAPTURE_TIME_RE = re.compile(
    r"\b(today|tomorrow)\s+(?:at|by|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)
_CAPTURE_STANDALONE_TIME_RE = re.compile(
    r"\b(?:at|by|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
_CAPTURE_WEEKDAY_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)
_FAMILY_DETAIL_RE = re.compile(
    r"\b(send|text|message)\b.*\b(mom|mother|mama|mum|dad|father|parent|parents|wife|family)\b",
    re.IGNORECASE,
)
_MESSAGE_CONTENT_RE = re.compile(
    r"\b(say|tell|ask|about|regarding|that)\b|[\"“”']",
    re.IGNORECASE,
)
_CAPTURE_DONE_MESSAGE_RE = re.compile(
    r"\b(message sent|sent (?:a )?message|texted|sent text|called|spoke to|asked about (?:her|his|their) health)\b",
    re.IGNORECASE,
)
_CAPTURE_MEAL_RE = re.compile(
    r"\b(ate|meal|breakfast|lunch|dinner|sandwich|sandwitch|food)\b",
    re.IGNORECASE,
)
_CAPTURE_WATER_RE = re.compile(
    r"\b(water|hydration|drank|drink|cup|cups|glass|glasses|bottle|bottles)\b",
    re.IGNORECASE,
)
_CAPTURE_WATER_COUNT_RE = re.compile(
    r"\b(\d+)\s*(?:cup|cups|glass|glasses|bottle|bottles)\b",
    re.IGNORECASE,
)
_NEW_CAPTURE_INTENT_RE = re.compile(
    r"\b(need to|want to|remind me|tomorrow|deadline|due|follow[- ]?up|invoice|deliver|submit|finish|ship|pay)\b",
    re.IGNORECASE,
)


async def _safe_record_capture_memory(**kwargs) -> None:
    try:
        await record_capture_memory(**kwargs)
    except Exception:
        return


async def _safe_record_daily_log_memory(**kwargs) -> None:
    try:
        await record_daily_log_memory(**kwargs)
    except Exception:
        return


def _infer_commitment_domain(text: str) -> str:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ["invoice", "payment", "client", "presentation", "one pager", "video", "mockup", "canva", "work"]):
        return "work"
    if any(token in lowered for token in ["pray", "quran", "deen", "salah"]):
        return "deen"
    if any(token in lowered for token in ["wife", "family", "kids", "home", "mother", "mom", "mama", "mum", "father", "dad", "parent"]):
        return "family"
    if any(token in lowered for token in ["sleep", "workout", "gym", "health", "meal"]):
        return "health"
    return "planning"


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


def _due_from_capture_match(match: re.Match[str], *, timezone_name: str, now_utc: datetime | None = None) -> datetime | None:
    clock = _parse_capture_clock(match.group(2), match.group(3), match.group(4))
    if not clock:
        return None
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    due_date = local_now.date() + timedelta(days=1 if match.group(1).lower() == "tomorrow" else 0)
    due_local = datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1])
    return due_local.astimezone(timezone.utc).replace(tzinfo=None)


def _standalone_due_from_capture_match(
    match: re.Match[str],
    *,
    text: str,
    timezone_name: str,
    now_utc: datetime | None = None,
) -> datetime | None:
    lowered = text.lower()
    if "today" not in lowered and "tomorrow" not in lowered:
        return None
    clock = _parse_capture_clock(match.group(1), match.group(2), match.group(3))
    if not clock:
        return None
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    due_date = local_now.date() + timedelta(days=1 if "tomorrow" in lowered and "today" not in lowered else 0)
    due_local = datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1])
    return due_local.astimezone(timezone.utc).replace(tzinfo=None)


def _weekday_due_from_capture_message(
    message: str,
    *,
    timezone_name: str,
    now_utc: datetime | None = None,
) -> datetime | None:
    weekday_match = _CAPTURE_WEEKDAY_RE.search(message or "")
    clock_match = _CAPTURE_STANDALONE_TIME_RE.search(message or "")
    if not weekday_match or not clock_match:
        return None
    clock = _parse_capture_clock(clock_match.group(1), clock_match.group(2), clock_match.group(3))
    if not clock:
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
    tz = _resolve_tz(timezone_name)
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    days_ahead = (target_weekday - local_now.weekday()) % 7
    due_date = local_now.date() + timedelta(days=days_ahead)
    due_local = datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1])
    if due_local <= local_now:
        due_local += timedelta(days=7)
    return due_local.astimezone(timezone.utc).replace(tzinfo=None)


async def _infer_capture_due_at(message: str, provided_due_at: datetime | None, timezone_name: str | None) -> datetime | None:
    if provided_due_at is not None:
        return provided_due_at
    effective_timezone = await get_commitment_timezone(timezone_name)
    match = _CAPTURE_TIME_RE.search(message)
    if match:
        return _due_from_capture_match(match, timezone_name=effective_timezone)
    standalone = _CAPTURE_STANDALONE_TIME_RE.search(message)
    if standalone:
        standalone_due = _standalone_due_from_capture_match(standalone, text=message, timezone_name=effective_timezone)
        if standalone_due:
            return standalone_due
    weekday_due = _weekday_due_from_capture_message(message, timezone_name=effective_timezone)
    if weekday_due:
        return weekday_due
    return None


def _priority_overrides_for_capture(message: str, due_at: datetime | None) -> dict:
    domain = _infer_commitment_domain(message)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    due_utc = due_at.astimezone(timezone.utc).replace(tzinfo=None) if due_at and due_at.tzinfo else due_at
    due_soon = due_utc is not None and due_utc <= now_utc + timedelta(hours=24)
    priority = "high" if due_soon else "medium"
    score = 82 if due_soon else 55
    signals = ["explicit deadline within 24h"] if due_soon else ["captured commitment"]
    if domain in {"family", "deen", "health"}:
        score = min(100, score + 8)
        signals.append(f"life anchor:{domain}")
    return {
        "domain": domain,
        "priority": priority,
        "priority_score": score,
        "priority_reason": f"Priority {score}/100 from {', '.join(signals)}.",
    }


def _detail_questions_for_capture(message: str, domain: str) -> list[str]:
    if domain != "family" or not _FAMILY_DETAIL_RE.search(message) or _MESSAGE_CONTENT_RE.search(message):
        return []
    return ["What should the message say, or what topic should it cover?"]


def _hydration_count_from_capture(message: str) -> int:
    match = _CAPTURE_WATER_COUNT_RE.search(message)
    if not match:
        return 1
    return max(1, min(12, int(match.group(1))))


def _looks_like_capture_update_only(message: str, *, handled: bool) -> bool:
    if not handled:
        return False
    return not _NEW_CAPTURE_INTENT_RE.search(message)


async def _complete_matching_family_message_item(message: str) -> LifeItem | None:
    if not _CAPTURE_DONE_MESSAGE_RE.search(message):
        return None
    async with async_session() as db:
        result = await db.execute(
            select(LifeItem)
            .where(LifeItem.status == "open")
            .where(LifeItem.domain == "family")
            .order_by(LifeItem.due_at.is_(None), LifeItem.due_at.asc(), LifeItem.updated_at.asc())
        )
        candidates = list(result.scalars().all())
    if not candidates:
        return None
    message_candidates = [
        item
        for item in candidates
        if any(token in f"{item.title} {item.notes or ''}".lower() for token in ["message", "text", "mother", "mom", "family"])
    ]
    item = (message_candidates or candidates)[0]
    _, updated = await add_checkin(
        item.id,
        LifeCheckinCreate(result="done", note=message.strip()[:500]),
    )
    async with async_session() as db:
        entry_result = await db.execute(select(IntakeEntry).where(IntakeEntry.linked_life_item_id == item.id))
        entries = list(entry_result.scalars().all())
    for entry in entries:
        await update_intake_entry(entry.id, IntakeEntryUpdate(status="processed", follow_up_questions=[]))
    return updated


async def _apply_quick_updates_from_capture(message: str) -> dict:
    logged_signals: list[str] = []
    completed_items: list[LifeItem] = []
    skipped_signals: list[str] = []
    note = message.strip()[:500]
    try:
        agenda = await get_today_agenda()
        scorecard_notes = dict(getattr(agenda.get("scorecard"), "notes_json", None) or {})
    except Exception:
        scorecard_notes = {}

    completed = await _complete_matching_family_message_item(message)
    if completed:
        completed_items.append(completed)
        logged_signals.append("completed family message")
        if scorecard_notes.get("family_note") == note:
            skipped_signals.append("family already logged")
        else:
            await log_daily_signal(DailyLogCreate(kind="family", done=True, note=note))
            logged_signals.append("family")
        if completed.priority == "high":
            priority_note = f"Completed #{completed.id}: {completed.title}"
            if scorecard_notes.get("priority_note") == priority_note:
                skipped_signals.append("priority already logged")
            else:
                await log_daily_signal(DailyLogCreate(kind="priority", count=1, note=priority_note))
                logged_signals.append("priority")

    if _CAPTURE_MEAL_RE.search(message):
        if scorecard_notes.get("last_meal_note") == note:
            skipped_signals.append("meal already logged")
        else:
            await log_daily_signal(DailyLogCreate(kind="meal", count=1, note=note))
            logged_signals.append("meal")

    if _CAPTURE_WATER_RE.search(message):
        count = _hydration_count_from_capture(message)
        if scorecard_notes.get("last_hydration_note") == note:
            skipped_signals.append("hydration already logged")
        else:
            await log_daily_signal(DailyLogCreate(kind="hydration", count=count, note=note))
            logged_signals.append(f"hydration x{count}")

    return {
        "handled": bool(logged_signals or skipped_signals or completed_items),
        "logged_signals": logged_signals,
        "skipped_signals": skipped_signals,
        "completed_items": completed_items,
    }


def _title_from_capture(text: str) -> str:
    for line in str(text or "").splitlines():
        cleaned = line.strip(" #-*\t")
        if len(cleaned) >= 4:
            return cleaned[:120]
    return "Capture"


def _select_capture_route(data: UnifiedCaptureRequest) -> str:
    hint = str(data.route_hint or "auto").strip().lower()
    if hint in {"intake", "commitment", "memory"}:
        return hint
    text = str(data.message or "").strip()
    if data.due_at is not None or _CAPTURE_COMMITMENT_RE.search(text):
        return "commitment"
    if _CAPTURE_MEMORY_RE.search(text):
        return "memory"
    return "intake"


def _needs_answer(entries: list[IntakeEntryResponse]) -> int:
    return len([entry for entry in entries if entry.status == "clarifying" or entry.follow_up_questions])


async def _force_ready_deadlined_commitment(entry_id: int, *, title: str):
    clean_title = str(title or "").strip()[:300] or "Captured commitment"
    domain = _infer_commitment_domain(clean_title)
    priority_overrides = _priority_overrides_for_capture(clean_title, None)
    return await update_intake_entry(
        entry_id,
        IntakeEntryUpdate(
            title=clean_title,
            summary=f"Follow through on: {clean_title}",
            domain=domain,
            kind="commitment",
            status="ready",
            desired_outcome=f"{clean_title} completed on time",
            next_action=f"Start the first visible step for: {clean_title}",
            follow_up_questions=[],
            promotion_payload={
                "title": clean_title,
                "kind": "task",
                "domain": domain,
                "priority": priority_overrides["priority"],
                "priority_score": priority_overrides["priority_score"],
                "priority_reason": priority_overrides["priority_reason"],
                "next_action": f"Start the first visible step for: {clean_title}",
            },
        ),
    )


async def _apply_commitment_capture_overrides(
    *,
    entry_id: int | None,
    life_item_id: int | None,
    message: str,
    due_at: datetime | None,
) -> None:
    overrides = _priority_overrides_for_capture(message, due_at)
    questions = _detail_questions_for_capture(message, overrides["domain"])
    if life_item_id:
        update_values = {
            "domain": overrides["domain"],
            "priority": overrides["priority"],
            "priority_score": overrides["priority_score"],
            "priority_reason": overrides["priority_reason"],
        }
        if due_at is not None:
            update_values["due_at"] = due_at
        update_payload = LifeItemUpdate(**update_values)
        await update_life_item(life_item_id, update_payload)
    if entry_id and questions:
        await update_intake_entry(
            entry_id,
            IntakeEntryUpdate(
                status="clarifying",
                follow_up_questions=questions,
            ),
        )


def _should_promote_commitment_entry(entry, *, due_at) -> bool:
    if not entry or entry.linked_life_item_id:
        return False
    if entry.status == "ready":
        return True
    if entry.status != "clarifying" or due_at is None:
        return False
    payload = dict(entry.promotion_payload_json or {})
    title = str(payload.get("title") or entry.title or "").strip()
    kind = str(payload.get("kind") or entry.kind or "").strip().lower()
    domain = str(payload.get("domain") or entry.domain or "").strip().lower()
    if len(title) < 3:
        return False
    return kind in {"commitment", "task", "habit", "routine"} and bool(domain)


def _commitment_followup_note(entry: IntakeEntry | None) -> str | None:
    if not entry or not entry.follow_up_questions_json:
        return None
    questions = [str(question).strip() for question in entry.follow_up_questions_json if str(question).strip()]
    if not questions:
        return None
    entry_context = {
        "title": entry.title,
        "domain": entry.domain,
        "kind": entry.kind,
        "status": entry.status,
        "original_capture": entry.raw_text,
        "summary": entry.summary,
        "desired_outcome": entry.desired_outcome,
        "next_action": entry.next_action,
        "open_questions": questions,
    }
    return (
        "This turn is a follow-up answer for an existing clarifying commitment. "
        "Merge the user's new message with the existing commitment below. "
        "If the new message answers the open questions, return status=ready and follow_up_questions=[]. "
        "Do not repeat questions that the user already answered. "
        "If timing is split across the original capture and this follow-up, combine them.\n"
        f"Existing commitment: {entry_context}"
    )


@router.get("/items", response_model=list[LifeItemResponse], dependencies=[Depends(require_api_token)])
async def get_items(
    domain: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    items = await list_life_items(domain=domain, status=status)
    return [LifeItemResponse.model_validate(item) for item in items]


@router.post("/items", response_model=LifeItemResponse, dependencies=[Depends(require_api_token)])
async def post_item(data: LifeItemCreate):
    item = await create_life_item(data)
    return LifeItemResponse.model_validate(item)


@router.put("/items/{item_id}", response_model=LifeItemResponse, dependencies=[Depends(require_api_token)])
async def put_item(item_id: int, data: LifeItemUpdate):
    item = await update_life_item(item_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Life item not found")
    return LifeItemResponse.model_validate(item)


@router.post("/items/{item_id}/snooze", response_model=LifeItemResponse, dependencies=[Depends(require_api_token)])
async def post_snooze_item(item_id: int, data: LifeItemSnoozeRequest):
    item = await snooze_life_item(
        item_id,
        due_at=data.due_at,
        timezone_name=data.timezone,
        source=data.source,
        note=data.note,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Life item not found")
    return LifeItemResponse.model_validate(item)


@router.post(
    "/items/{item_id}/checkin",
    response_model=LifeCheckinResponse,
    dependencies=[Depends(require_api_token)],
)
async def post_checkin(item_id: int, data: LifeCheckinCreate):
    checkin, item = await add_checkin(item_id, data)
    if not checkin:
        raise HTTPException(status_code=404, detail="Life item not found")
    return LifeCheckinResponse.model_validate(checkin)


@router.post("/daily-log", response_model=DailyLogResponse, dependencies=[Depends(require_api_token)])
async def post_daily_log(data: DailyLogCreate):
    try:
        result = await log_daily_signal(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _safe_record_daily_log_memory(
        raw_logs=[data.model_dump(exclude_none=True)],
        result_text=result["message"],
        source_agent="webui",
        source="webui_daily_log",
    )

    return DailyLogResponse(
        kind=result["kind"],
        message=result["message"],
        scorecard=DailyScorecardResponse.model_validate(result["scorecard"]),
        rescue_plan=RescuePlanResponse.model_validate(result["rescue_plan"]),
        sleep_protocol=SleepProtocolResponse.model_validate(result["sleep_protocol"]) if result.get("sleep_protocol") else None,
        streaks=result.get("streaks") or [],
        trend_summary=result.get("trend_summary"),
    )


@router.get("/today", response_model=TodayAgendaResponse, dependencies=[Depends(require_api_token)])
async def get_today():
    agenda = await get_today_agenda()
    return TodayAgendaResponse(
        timezone=agenda["timezone"],
        now=agenda["now"],
        top_focus=[LifeItemResponse.model_validate(item) for item in agenda["top_focus"]],
        due_today=[LifeItemResponse.model_validate(item) for item in agenda["due_today"]],
        overdue=[LifeItemResponse.model_validate(item) for item in agenda["overdue"]],
        domain_summary=agenda["domain_summary"],
        intake_summary=agenda.get("intake_summary") or {},
        ready_intake=[IntakeEntryResponse.model_validate(item) for item in agenda.get("ready_intake") or []],
        memory_review=[SharedMemoryProposalResponse.model_validate(item) for item in agenda.get("memory_review") or []],
        scorecard=DailyScorecardResponse.model_validate(agenda["scorecard"]) if agenda.get("scorecard") else None,
        next_prayer=NextPrayerResponse.model_validate(agenda["next_prayer"]) if agenda.get("next_prayer") else None,
        rescue_plan=RescuePlanResponse.model_validate(agenda["rescue_plan"]) if agenda.get("rescue_plan") else None,
        sleep_protocol=SleepProtocolResponse.model_validate(agenda["sleep_protocol"]) if agenda.get("sleep_protocol") else None,
        streaks=agenda.get("streaks") or [],
        trend_summary=agenda.get("trend_summary"),
    )


@router.post("/capture", response_model=UnifiedCaptureResponse, dependencies=[Depends(require_api_token)])
async def capture_life(data: UnifiedCaptureRequest):
    message = (data.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    quick_updates = await _apply_quick_updates_from_capture(message)
    if _looks_like_capture_update_only(message, handled=quick_updates["handled"]):
        completed_items = [
            LifeItemResponse.model_validate(item)
            for item in quick_updates["completed_items"]
            if item is not None
        ]
        signals = quick_updates["logged_signals"]
        skipped = quick_updates.get("skipped_signals") or []
        status_text = ", ".join(signals + skipped) if signals or skipped else "daily status"
        await _safe_record_capture_memory(
            raw_text=message,
            source=data.source or "api",
            source_agent="daily-log-capture",
            source_session_id=data.session_id,
            event_type="daily_log_capture",
        )
        return UnifiedCaptureResponse(
            route="daily_log",
            response=(
                "Updated Today: "
                f"{status_text}. "
                f"Completed {len(completed_items)} item(s)."
            ),
            logged_signals=signals,
            completed_items=completed_items,
        )

    route = _select_capture_route(data)
    if route == "commitment":
        inferred_due_at = await _infer_capture_due_at(message, data.due_at, data.timezone)
        result = await capture_commitment(
            CommitmentCaptureRequest(
                message=message,
                raw_message=message,
                session_id=data.session_id,
                new_session=data.new_session,
                source=data.source or "api",
                due_at=inferred_due_at,
                timezone=data.timezone,
                target_channel=data.target_channel,
                target_channel_id=data.target_channel_id,
            )
        )
        entries = [result.entry] if result.entry else []
        life_items = [result.life_item] if result.life_item else []
        entry_obj = await get_intake_entry(result.entry.id) if result.entry and result.entry.id else None
        item_obj = None
        if result.life_item and result.life_item.id:
            async with async_session() as db:
                item_result = await db.execute(select(LifeItem).where(LifeItem.id == result.life_item.id))
                item_obj = item_result.scalar_one_or_none()
        await _safe_record_capture_memory(
            raw_text=message,
            source=data.source or "api",
            source_agent=COMMITMENT_AGENT_NAME,
            source_session_id=result.session_id,
            entry=entry_obj,
            life_item=item_obj,
            event_type="commitment_capture",
        )
        return UnifiedCaptureResponse(
            route="commitment",
            response=result.response,
            session_id=result.session_id,
            session_title=result.session_title,
            entry=result.entry,
            entries=entries,
            life_item=result.life_item,
            life_items=life_items,
            follow_up_job=result.follow_up_job,
            auto_promoted_count=1 if result.auto_promoted else 0,
            needs_follow_up=result.needs_follow_up,
            needs_answer_count=_needs_answer(entries),
        )

    if route == "memory":
        try:
            event, proposals, intake_entry_ids = await capture_meeting_summary(
                MeetingIntakeRequest(
                    summary=message,
                    title=_title_from_capture(message),
                    domain=_infer_commitment_domain(message),
                    source=data.source or "api",
                    source_agent="wiki-curator",
                    session_id=data.session_id,
                    tags=["unified-capture"],
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await _safe_record_capture_memory(
            raw_text=message,
            source=data.source or "api",
            source_agent="wiki-curator",
            source_session_id=data.session_id,
            event_type="memory_capture",
        )
        entries = []
        for entry_id in intake_entry_ids[:5]:
            entry = await get_intake_entry(entry_id)
            if entry:
                entries.append(IntakeEntryResponse.model_validate(entry))
        return UnifiedCaptureResponse(
            route="memory",
            response=(
                f"Captured memory review event #{event.id}. "
                f"{len(proposals)} memory review item(s) ready."
            ),
            event=ContextEventResponse.model_validate(event),
            entries=entries,
            entry=entries[0] if entries else None,
            wiki_proposals=[SharedMemoryProposalResponse.model_validate(row) for row in proposals],
            needs_answer_count=_needs_answer(entries),
        )

    result = await capture_inbox(
        IntakeCaptureRequest(
            message=message,
            session_id=data.session_id,
            new_session=data.new_session,
            source=data.source or "api",
        )
    )
    entries = result.entries or ([result.entry] if result.entry else [])
    entry_obj = await get_intake_entry(entries[0].id) if entries else None
    await _safe_record_capture_memory(
        raw_text=message,
        source=data.source or "api",
        source_agent="intake-inbox",
        source_session_id=result.session_id,
        entry=entry_obj,
        event_type="intake_capture",
    )
    return UnifiedCaptureResponse(
        route="intake",
        response=result.response,
        session_id=result.session_id,
        session_title=result.session_title,
        entry=result.entry,
        entries=entries,
        life_items=result.life_items,
        wiki_proposals=result.wiki_proposals,
        auto_promoted_count=result.auto_promoted_count,
        needs_follow_up=bool(_needs_answer(entries)),
        needs_answer_count=_needs_answer(entries),
    )


@router.get(
    "/items/{item_id}/progress",
    response_model=GoalProgressResponse,
    dependencies=[Depends(require_api_token)],
)
async def get_item_progress(item_id: int):
    result = await get_goal_progress(item_id)
    if not result:
        raise HTTPException(status_code=404, detail="Life item not found")
    return GoalProgressResponse.model_validate(result)


@router.get("/inbox", response_model=list[IntakeEntryResponse], dependencies=[Depends(require_api_token)])
async def get_inbox(
    status: str | None = Query(default=None),
    session_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
):
    rows = await list_intake_entries(status=status, session_id=session_id, limit=limit)
    return [IntakeEntryResponse.model_validate(row) for row in rows]


@router.post("/inbox/capture", response_model=IntakeCaptureResponse, dependencies=[Depends(require_api_token)])
async def capture_inbox(data: IntakeCaptureRequest):
    message = (data.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    session_id = data.session_id
    if data.new_session:
        title = generate_title_from_prompts([message])
        session = await create_session(agent_name="intake-inbox", title=title)
        session_id = session.id

    result = await handle_message(
        agent_name="intake-inbox",
        user_message=message,
        approval_policy="never",
        source=data.source or "api",
        session_id=session_id,
        session_enabled=True,
    )
    if result.get("error_code") == "session_not_found":
        raise HTTPException(status_code=404, detail=result["response"])
    if result.get("error_code") == "memory_unavailable":
        raise HTTPException(status_code=503, detail=result["response"])
    if result.get("error_code") == "state_packet_unavailable":
        raise HTTPException(status_code=503, detail=result["response"])

    entry = None
    if result.get("session_id"):
        entry = await get_latest_intake_entry_for_session(
            result["session_id"],
            source_agent="intake-inbox",
        )
    synthesis = await synthesize_intake_capture(raw_message=message, primary_entry=entry)
    entries = synthesis.get("entries") or ([entry] if entry else [])
    await _safe_record_capture_memory(
        raw_text=message,
        source=data.source or "api",
        source_agent="intake-inbox",
        source_session_id=result.get("session_id"),
        entry=entries[0] if entries else None,
        event_type="intake_capture",
    )

    return IntakeCaptureResponse(
        response=result["response"],
        session_id=result.get("session_id"),
        session_title=result.get("session_title"),
        entry=IntakeEntryResponse.model_validate(entries[0]) if entries else None,
        entries=[IntakeEntryResponse.model_validate(row) for row in entries],
        life_items=[LifeItemResponse.model_validate(item) for item in synthesis.get("life_items") or []],
        wiki_proposals=[SharedMemoryProposalResponse.model_validate(row) for row in synthesis.get("wiki_proposals") or []],
        auto_promoted_count=int(synthesis.get("auto_promoted_count") or 0),
    )


@router.post("/commitments/capture", response_model=CommitmentCaptureResponse, dependencies=[Depends(require_api_token)])
async def capture_commitment(data: CommitmentCaptureRequest):
    message = (data.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    raw_message = (data.raw_message or message).strip()

    session_id = data.session_id
    if data.new_session:
        title = generate_title_from_prompts([raw_message])
        session = await create_session(agent_name=COMMITMENT_AGENT_NAME, title=title)
        session_id = session.id

    prior_entry = None
    if session_id and not data.new_session:
        prior_entry = await get_latest_intake_entry_for_session(
            session_id,
            source_agent=COMMITMENT_AGENT_NAME,
        )
    capture_context_message = raw_message
    if prior_entry and prior_entry.raw_text:
        capture_context_message = f"{prior_entry.raw_text}\nFollow-up answer: {raw_message}"

    handle_kwargs = {
        "agent_name": COMMITMENT_AGENT_NAME,
        "user_message": raw_message,
        "approval_policy": "never",
        "source": data.source or "api",
        "session_id": session_id,
        "session_enabled": True,
    }
    followup_note = _commitment_followup_note(prior_entry)
    if followup_note:
        handle_kwargs["transient_system_note"] = followup_note
    result = await handle_message(**handle_kwargs)
    if result.get("error_code") == "session_not_found":
        raise HTTPException(status_code=404, detail=result["response"])
    if result.get("error_code") == "memory_unavailable":
        raise HTTPException(status_code=503, detail=result["response"])
    if result.get("error_code") == "state_packet_unavailable":
        raise HTTPException(status_code=503, detail=result["response"])

    entry = None
    if result.get("session_id"):
        entry = await get_latest_intake_entry_for_session(
            result["session_id"],
            source_agent=COMMITMENT_AGENT_NAME,
        )

    life_item = None
    follow_up_job = None
    auto_promoted = False
    effective_timezone = await get_commitment_timezone(data.timezone)
    inferred_due_at = await _infer_capture_due_at(capture_context_message, data.due_at, effective_timezone)
    priority_overrides = _priority_overrides_for_capture(capture_context_message, inferred_due_at)
    if entry and inferred_due_at is not None and not entry.linked_life_item_id and not _should_promote_commitment_entry(entry, due_at=inferred_due_at):
        entry = await _force_ready_deadlined_commitment(entry.id, title=message)
    if entry and entry.linked_life_item_id:
        if inferred_due_at is not None:
            await update_life_item(
                entry.linked_life_item_id,
                LifeItemUpdate(due_at=inferred_due_at, status="open"),
            )
        async with async_session() as db:
            item_result = await db.execute(select(LifeItem).where(LifeItem.id == entry.linked_life_item_id))
            life_item = item_result.scalar_one_or_none()
        if life_item:
            follow_up_job = await upsert_follow_up_job(
                life_item.id,
                timezone_name=effective_timezone,
                target_channel=data.target_channel,
                target_channel_id=data.target_channel_id,
            )
            async with async_session() as db:
                refreshed = await db.execute(select(LifeItem).where(LifeItem.id == life_item.id))
                life_item = refreshed.scalar_one_or_none()
    elif entry and _should_promote_commitment_entry(entry, due_at=inferred_due_at):
        overrides = dict(priority_overrides)
        if inferred_due_at is not None:
            overrides["due_at"] = inferred_due_at
        entry, life_item = await promote_intake_entry(entry.id, overrides=overrides)
        auto_promoted = bool(life_item)
        if life_item:
            follow_up_job = await upsert_follow_up_job(
                life_item.id,
                timezone_name=effective_timezone,
                target_channel=data.target_channel,
                target_channel_id=data.target_channel_id,
            )
            async with async_session() as db:
                refreshed = await db.execute(select(LifeItem).where(LifeItem.id == life_item.id))
                life_item = refreshed.scalar_one_or_none()
    if entry and life_item:
        await _apply_commitment_capture_overrides(
            entry_id=entry.id,
            life_item_id=life_item.id,
            message=capture_context_message,
            due_at=inferred_due_at,
        )
        async with async_session() as db:
            refreshed_entry = await db.execute(select(IntakeEntry).where(IntakeEntry.id == entry.id))
            refreshed_item = await db.execute(select(LifeItem).where(LifeItem.id == life_item.id))
            entry = refreshed_entry.scalar_one_or_none()
            life_item = refreshed_item.scalar_one_or_none()

    needs_follow_up = bool(entry and entry.status == "clarifying")
    await _safe_record_capture_memory(
        raw_text=capture_context_message,
        source=data.source or "api",
        source_agent=COMMITMENT_AGENT_NAME,
        source_session_id=result.get("session_id"),
        entry=entry,
        life_item=life_item,
        event_type="commitment_capture",
    )
    return CommitmentCaptureResponse(
        response=result["response"],
        session_id=result.get("session_id"),
        session_title=result.get("session_title"),
        entry=IntakeEntryResponse.model_validate(entry) if entry else None,
        life_item=LifeItemResponse.model_validate(life_item) if life_item else None,
        follow_up_job=ScheduledJobResponse.model_validate(follow_up_job) if follow_up_job else None,
        auto_promoted=auto_promoted,
        needs_follow_up=needs_follow_up,
    )


@router.get("/inbox/{entry_id}", response_model=IntakeEntryResponse, dependencies=[Depends(require_api_token)])
async def get_inbox_entry(entry_id: int):
    entry = await get_intake_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return IntakeEntryResponse.model_validate(entry)


@router.put("/inbox/{entry_id}", response_model=IntakeEntryResponse, dependencies=[Depends(require_api_token)])
async def put_inbox_entry(entry_id: int, data: IntakeEntryUpdate):
    entry = await update_intake_entry(entry_id, data)
    if not entry:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return IntakeEntryResponse.model_validate(entry)


@router.post(
    "/inbox/{entry_id}/promote",
    response_model=IntakePromoteResponse,
    dependencies=[Depends(require_api_token)],
)
async def promote_inbox_entry(entry_id: int, data: IntakePromoteRequest):
    entry, item = await promote_intake_entry(entry_id, overrides=data.model_dump(exclude_unset=True))
    if not entry or not item:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return IntakePromoteResponse(
        entry=IntakeEntryResponse.model_validate(entry),
        life_item=LifeItemResponse.model_validate(item),
    )


@router.get("/coach/daily-focus", response_model=DailyFocusCoachResponse, dependencies=[Depends(require_api_token)])
async def get_daily_focus():
    return DailyFocusCoachResponse.model_validate(await get_daily_focus_coach())


@router.get("/coach/weekly-review", response_model=WeeklyCommitmentReviewResponse, dependencies=[Depends(require_api_token)])
async def get_weekly_review():
    return WeeklyCommitmentReviewResponse.model_validate(await get_weekly_commitment_review())
