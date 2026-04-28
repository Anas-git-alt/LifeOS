"""Batch capture splitting and raw-capture persistence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from app.database import async_session
from app.models import CaptureItemResponse, ContextEvent
from app.services.provider_router import chat_completion

CAPTURE_ITEM_TYPES = {
    "commitment",
    "reminder",
    "task",
    "goal",
    "habit",
    "routine",
    "memory",
    "meeting_note",
    "daily_log",
    "question",
    "idea",
}
CAPTURE_DOMAINS = {"deen", "family", "work", "health", "planning"}
CAPTURE_DESTINATIONS = {"life_item", "memory_review", "meeting_context", "daily_log", "needs_answer"}
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_MEANINGFUL_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_RESIDUE_SPLIT_RE = re.compile(r"(?:\n+|;|\. |\s+-\s+|\s+(?:and then|then|also|plus)\s+|,\s*)", re.IGNORECASE)


def _clean_text(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").strip().split())
    if limit is not None:
        return text[:limit]
    return text


def _title_from_text(text: str) -> str:
    cleaned = _clean_text(text, limit=120)
    return cleaned or "Capture item"


def _clean_span(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "").strip()
    if limit is not None:
        return text[:limit]
    return text


def _domain_from_text(value: str) -> str:
    lowered = value.lower()
    if any(token in lowered for token in ("pray", "quran", "deen", "salah", "adhan")):
        return "deen"
    if any(token in lowered for token in ("wife", "family", "mother", "mom", "father", "dad", "kids", "home")):
        return "family"
    if any(token in lowered for token in ("invoice", "client", "meeting", "deploy", "staging", "work", "hr", "project")):
        return "work"
    if any(token in lowered for token in ("sleep", "meal", "protein", "water", "hydration", "gym", "training", "doctor", "health")):
        return "health"
    return "planning"


def _type_from_text(value: str) -> str:
    lowered = value.lower()
    if any(token in lowered for token in ("remember that", "preference", "durable", "always", "usually")):
        return "memory"
    if any(token in lowered for token in ("meeting", "decision", "retro", "standup", "notes")):
        return "meeting_note"
    if any(token in lowered for token in ("remind me", "deadline", "due", "tomorrow", "follow up", "follow-up")):
        return "reminder"
    if any(token in lowered for token in ("habit", "routine", "every day", "daily")):
        return "habit"
    if any(token in lowered for token in ("goal", "aim", "target")):
        return "goal"
    if lowered.endswith("?") or lowered.startswith(("what ", "when ", "which ", "how ", "why ")):
        return "question"
    if any(token in lowered for token in ("log", "slept", "ate", "drank", "trained", "prayed")):
        return "daily_log"
    if any(token in lowered for token in ("idea", "maybe", "could")):
        return "idea"
    if any(token in lowered for token in ("promise", "committed", "i will", "need to", "must")):
        return "commitment"
    return "task"


def _normalise_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.55
    if number > 1:
        number = number / 100.0
    return max(0.0, min(number, 1.0))


def _parse_due_at(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    return parsed


def _normalise_questions(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [_clean_text(item, limit=240) for item in value if _clean_text(item)]
    if isinstance(value, str):
        return [_clean_text(line, limit=240) for line in value.splitlines() if _clean_text(line)]
    return []


def _destination_for_item(item_type: str, *, confidence: float, needs_follow_up: bool) -> str:
    if item_type == "meeting_note":
        return "meeting_context"
    if item_type == "memory":
        return "memory_review"
    if item_type == "daily_log":
        return "daily_log"
    if item_type == "question":
        return "needs_answer"
    if item_type in {"commitment", "reminder"}:
        return "life_item"
    if needs_follow_up or confidence < 0.72:
        return "needs_answer"
    return "life_item"


def _meaningful_fragment(fragment: str) -> bool:
    words = _MEANINGFUL_WORD_RE.findall(fragment)
    if len(words) >= 3:
        return True
    return len(words) >= 2 and len(fragment.strip()) >= 14


def _merge_residue(residue: list[str], fragment: str) -> None:
    cleaned = _clean_text(fragment, limit=500)
    if not cleaned or not _meaningful_fragment(cleaned):
        return
    lowered = cleaned.lower()
    if any(lowered == item.lower() for item in residue):
        return
    residue.append(cleaned)


def _covered_intervals(message: str, spans: list[str]) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    search_start = 0
    for span in spans:
        if not span:
            continue
        index = message.find(span, search_start)
        if index < 0:
            index = message.find(span)
        if index < 0:
            continue
        intervals.append((index, index + len(span)))
        search_start = index + len(span)
    return intervals


def _residue_from_coverage(message: str, spans: list[str], raw_residue: list[str]) -> list[str]:
    residue: list[str] = []
    for item in raw_residue:
        _merge_residue(residue, item)
    intervals = sorted(_covered_intervals(message, spans))
    if not intervals:
        if not residue:
            _merge_residue(residue, message)
        return residue

    cursor = 0
    for start, end in intervals:
        if start > cursor:
            gap = message[cursor:start]
            for part in _RESIDUE_SPLIT_RE.split(gap):
                _merge_residue(residue, part)
        cursor = max(cursor, end)
    if cursor < len(message):
        for part in _RESIDUE_SPLIT_RE.split(message[cursor:]):
            _merge_residue(residue, part)
    return residue


def _fallback_capture_item(message: str) -> CaptureItemResponse:
    source_span = _clean_span(message, limit=500) or "Capture needs review"
    return CaptureItemResponse(
        type=_type_from_text(source_span),
        domain=_domain_from_text(source_span),
        title=_title_from_text(source_span),
        summary="Capture needs follow-up before LifeOS can track it safely.",
        source_span=source_span,
        confidence=0.25,
        due_at=None,
        recurrence=None,
        needs_follow_up=True,
        follow_up_questions=["What should LifeOS capture or track from this message?"],
        suggested_destination="needs_answer",
    )


def _normalise_capture_item(item: dict[str, Any], message: str) -> CaptureItemResponse:
    source_span = _clean_span(item.get("source_span") or item.get("span") or item.get("text"), limit=500)
    if not source_span:
        source_span = _clean_span(message, limit=500)
    item_type = _clean_text(item.get("type") or item.get("kind") or "").lower().replace(" ", "_")
    if item_type not in CAPTURE_ITEM_TYPES:
        item_type = _type_from_text(" ".join(filter(None, [source_span, _clean_text(item.get("title")), _clean_text(item.get("summary"))])))
    domain = _clean_text(item.get("domain") or "").lower()
    if domain not in CAPTURE_DOMAINS:
        domain = _domain_from_text(" ".join(filter(None, [source_span, _clean_text(item.get("title")), _clean_text(item.get("summary"))])))
    confidence = _normalise_confidence(item.get("confidence"))
    follow_up_questions = _normalise_questions(item.get("follow_up_questions"))
    needs_follow_up = bool(item.get("needs_follow_up")) or bool(follow_up_questions)
    destination = _clean_text(item.get("suggested_destination") or item.get("destination")).lower().replace(" ", "_")
    if destination not in CAPTURE_DESTINATIONS:
        destination = _destination_for_item(item_type, confidence=confidence, needs_follow_up=needs_follow_up)
    return CaptureItemResponse(
        type=item_type,
        domain=domain,
        title=_clean_text(item.get("title"), limit=300) or _title_from_text(source_span),
        summary=_clean_text(item.get("summary"), limit=1000) or _clean_text(source_span, limit=1000),
        source_span=source_span,
        confidence=confidence,
        due_at=_parse_due_at(item.get("due_at")),
        recurrence=_clean_text(item.get("recurrence"), limit=240) or None,
        needs_follow_up=needs_follow_up,
        follow_up_questions=follow_up_questions[:3],
        suggested_destination=destination,
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text.strip():
        return None
    match = _JSON_BLOCK_RE.search(text.strip())
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def create_raw_capture_event(
    *,
    message: str,
    source: str,
    source_session_id: int | None,
    source_message_id: str | None,
    source_channel_id: str | None,
) -> ContextEvent:
    async with async_session() as db:
        event = ContextEvent(
            event_type="raw_capture",
            source=source or "api",
            source_agent="capture-v2",
            source_session_id=source_session_id,
            title=_title_from_text(message),
            summary=_clean_text(message, limit=2000),
            raw_text=message,
            domain=_domain_from_text(message),
            status="new",
            metadata_json={
                "source_message_id": source_message_id,
                "source_channel_id": source_channel_id,
            },
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event


async def update_raw_capture_event(event_id: int, *, metadata: dict[str, Any], status: str = "captured") -> ContextEvent | None:
    async with async_session() as db:
        row = await db.get(ContextEvent, event_id)
        if not row:
            return None
        next_metadata = dict(row.metadata_json or {})
        next_metadata.update(metadata)
        row.metadata_json = next_metadata
        row.status = status
        await db.commit()
        await db.refresh(row)
        return row


async def split_capture_message(
    *,
    message: str,
    timezone_name: str | None,
    route_hint: str | None = None,
) -> tuple[list[CaptureItemResponse], list[str]]:
    prompt = (
        "You are LifeOS Capture V2. Extract every important item from one messy capture message.\n"
        "Return JSON only with this exact shape:\n"
        "{"
        "\"captured_items\":[{"
        "\"type\":\"commitment|reminder|task|goal|habit|routine|memory|meeting_note|daily_log|question|idea\","
        "\"domain\":\"deen|family|work|health|planning\","
        "\"title\":\"...\","
        "\"summary\":\"...\","
        "\"source_span\":\"exact copied text from the original message\","
        "\"confidence\":0.0,"
        "\"due_at\":\"ISO-8601 datetime or null\","
        "\"recurrence\":\"string or null\","
        "\"needs_follow_up\":false,"
        "\"follow_up_questions\":[],"
        "\"suggested_destination\":\"life_item|memory_review|meeting_context|daily_log|needs_answer\""
        "}],"
        "\"uncaptured_residue\":[\"...\"]"
        "}\n"
        "Rules:\n"
        "- Capture every meaningful promise, reminder, task, goal, habit, routine, memory, meeting note, daily log, question, or idea.\n"
        "- Do not merge unrelated items.\n"
        "- Copy source_span verbatim from the message.\n"
        "- If a fragment is meaningful but ambiguous, still capture it and set needs_follow_up=true.\n"
        "- Put leftover meaningful text in uncaptured_residue.\n"
        "- If there is no residue, return an empty array.\n"
        f"- Local timezone: {timezone_name or 'Africa/Casablanca'}.\n"
        f"- Route hint: {route_hint or 'auto'}.\n"
        f"- Today UTC: {datetime.now(timezone.utc).isoformat()}.\n"
        f"Message:\n{message}"
    )
    raw = await chat_completion(
        messages=[
            {"role": "system", "content": "You return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        provider="openrouter",
        model="openrouter/free",
        fallback_provider="nvidia",
        fallback_model="meta/llama-3.1-8b-instruct",
        temperature=0.1,
        max_tokens=1800,
    )
    parsed = _extract_json(str(raw or "")) or {}
    raw_items = parsed.get("captured_items") or parsed.get("items") or []
    items = [_normalise_capture_item(item, message) for item in raw_items if isinstance(item, dict)]
    if not items:
        items = [_fallback_capture_item(message)]
    raw_residue = parsed.get("uncaptured_residue") or []
    if not isinstance(raw_residue, list):
        raw_residue = []
    residue = _residue_from_coverage(message, [item.source_span for item in items], [str(item) for item in raw_residue])
    return items[:12], residue[:8]
