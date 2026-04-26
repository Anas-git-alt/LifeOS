"""Raw life input synthesis into connected priorities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Agent, IntakeEntry, LifeItem, SharedMemoryPromoteRequest, SharedMemoryProposal
from app.services.intake import promote_intake_entry
from app.services.shared_memory import create_shared_memory_review_proposal, search_shared_memory
from app.services.vault import classify_note_path

VALID_DOMAINS = {"deen", "family", "work", "health", "planning"}
VALID_KINDS = {"idea", "task", "goal", "habit", "commitment", "routine", "note"}
PROMOTABLE_KINDS = {"task", "goal", "habit", "commitment", "routine"}
PRIORITY_BY_SCORE = ((75, "high"), (40, "medium"), (0, "low"))
BASE_SCORE = {"high": 78, "medium": 52, "low": 25}
TIME_PHRASE_RE = re.compile(
    r"\b(today|tomorrow)\s+(?:at|by|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)
BED_RE = re.compile(r"\bbed(?:time| target)?(?:\s+(?:is|at))?\s*(\d{1,2}:\d{2})\b", re.IGNORECASE)
WAKE_RE = re.compile(r"\bwake(?:\s*(?:time|target))?(?:\s+(?:is|at))?\s*(\d{1,2}:\d{2})\b", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
PLANNING_CONTEXT_RE = re.compile(
    r"\b(admin|errand|event|wedding|appointment|paper|papers|document|documents|"
    r"contract|tax|hr|treasury|dgi|shop|store|pickup|pick up|drop off|ironing|"
    r"suit|clothes|clothing|uat|staging|notes?)\b",
    re.IGNORECASE,
)
HEALTH_CONTEXT_RE = re.compile(r"\b(sleep|workout|gym|health|meal|protein|water|medicine|doctor)\b", re.IGNORECASE)
FAMILY_CONTEXT_RE = re.compile(r"\b(wife|family|kids|mother|mom|mama|mum|father|dad|parent|brother|sister)\b", re.IGNORECASE)
STOP_WORDS = {
    "after",
    "before",
    "today",
    "tomorrow",
    "target",
    "routine",
    "status",
    "summary",
    "priority",
    "high",
    "medium",
    "low",
}


def _clean(value: Any, *, limit: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _safe_domain(value: Any) -> str:
    candidate = str(value or "planning").strip().lower()
    return candidate if candidate in VALID_DOMAINS else "planning"


def _safe_domain_for_text(value: Any, text: str) -> str:
    domain = _safe_domain(value)
    lowered = str(text or "").lower()
    if domain == "health" and PLANNING_CONTEXT_RE.search(lowered) and not HEALTH_CONTEXT_RE.search(lowered):
        return "planning"
    if domain == "family" and PLANNING_CONTEXT_RE.search(lowered) and not FAMILY_CONTEXT_RE.search(lowered):
        return "planning"
    return domain


def _safe_kind(value: Any) -> str:
    candidate = str(value or "task").strip().lower()
    return candidate if candidate in VALID_KINDS else "task"


def _safe_status(value: Any) -> str:
    candidate = str(value or "ready").strip().lower()
    return candidate if candidate in {"raw", "clarifying", "ready", "processed", "parked", "archived"} else "ready"


def _priority_from_score(score: int) -> str:
    for threshold, label in PRIORITY_BY_SCORE:
        if score >= threshold:
            return label
    return "low"


def _coerce_score(value: Any) -> int | None:
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return None


def _coerce_due_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolve_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone)
    except Exception:
        return ZoneInfo("UTC")


def _parse_clock(hour_text: str, minute_text: str | None, meridian_text: str | None) -> tuple[int, int] | None:
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


def _item_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "summary", "desired_outcome", "next_action"))


def _item_tokens(item: dict[str, Any]) -> set[str]:
    return {token for token in WORD_RE.findall(_item_text(item).lower()) if token not in STOP_WORDS}


def _time_match_belongs_to_item(raw_message: str, match: re.Match[str], item: dict[str, Any]) -> bool:
    tokens = _item_tokens(item)
    if not tokens:
        return False
    context = raw_message[max(0, match.start() - 80):match.end()].lower()
    return bool(tokens.intersection(WORD_RE.findall(context)))


def _due_from_match(match: re.Match[str], *, now_utc: datetime) -> datetime | None:
    clock = _parse_clock(match.group(2), match.group(3), match.group(4))
    if not clock:
        return None
    tz = _resolve_tz()
    local_now = now_utc.astimezone(tz)
    due_date = local_now.date() + timedelta(days=1 if match.group(1).lower() == "tomorrow" else 0)
    due_local = datetime.combine(due_date, datetime.min.time(), tzinfo=tz).replace(hour=clock[0], minute=clock[1])
    return due_local.astimezone(timezone.utc)


def _infer_due_at(raw_message: str, item: dict[str, Any], *, now_utc: datetime) -> datetime | None:
    explicit = _coerce_due_at(item.get("due_at"))
    if explicit:
        return explicit
    item_match = TIME_PHRASE_RE.search(_item_text(item))
    if item_match:
        return _due_from_match(item_match, now_utc=now_utc)
    for raw_match in TIME_PHRASE_RE.finditer(raw_message):
        if _time_match_belongs_to_item(raw_message, raw_match, item):
            return _due_from_match(raw_match, now_utc=now_utc)
    return None


def _sleep_target(raw_message: str) -> tuple[str, str] | None:
    bed = BED_RE.search(raw_message)
    wake = WAKE_RE.search(raw_message)
    if not bed or not wake:
        return None
    return bed.group(1), wake.group(1)


def _looks_like_sleep_item(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("title", "summary", "desired_outcome", "next_action")).lower()
    return "sleep" in text or "bedtime" in text


def _looks_like_family_call_item(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("title", "summary", "desired_outcome", "next_action")).lower()
    return ("family" in text or _safe_domain(item.get("domain")) == "family") and "call" in text


def _family_call_detected(raw_message: str) -> bool:
    text = raw_message.lower()
    return "family" in text and "call" in text


def _max_score(value: Any, floor: int) -> int:
    coerced = _coerce_score(value)
    return max(floor, coerced or 0)


def _canonical_kind(item: dict[str, Any]) -> str:
    kind = _safe_kind(item.get("kind"))
    text = _item_text(item).lower()
    if kind == "habit" and any(token in text for token in ("invoice", "call family", "family call", "send ", "follow up")):
        return "task"
    return kind


def _augment_item_from_raw(item: dict[str, Any], raw_message: str) -> dict[str, Any]:
    enriched = dict(item)
    enriched["kind"] = _canonical_kind(enriched)
    if "invoice" in _item_text(enriched).lower():
        enriched["kind"] = "task"
        enriched["domain"] = "work"
    sleep_target = _sleep_target(raw_message)
    if sleep_target and _looks_like_sleep_item(enriched):
        bed, wake = sleep_target
        enriched.update(
            {
                "title": enriched.get("title") or "Fix bedtime routine",
                "kind": "habit",
                "domain": "health",
                "status": "ready",
                "desired_outcome": enriched.get("desired_outcome") or f"Sleep by {bed} and wake by {wake} consistently.",
                "next_action": enriched.get("next_action") or f"Set phone cutoff plus bedtime/wake alarms for {bed}/{wake}.",
                "follow_up_questions": [],
                "priority": "high",
                "priority_score": _max_score(enriched.get("priority_score"), 86),
                "priority_reason": enriched.get("priority_reason")
                or "Sleep target is concrete and affects energy, prayer timing, and next-day execution.",
            }
        )
    if _family_call_detected(raw_message) and _looks_like_family_call_item(enriched):
        enriched.update(
            {
                "title": enriched.get("title") or "Call family tomorrow after Asr",
                "kind": "task",
                "domain": "family",
                "status": "ready",
                "desired_outcome": enriched.get("desired_outcome") or "Family call completed.",
                "next_action": enriched.get("next_action") or "Call family tomorrow after Asr.",
                "follow_up_questions": [],
                "priority": "medium",
                "priority_score": _max_score(enriched.get("priority_score"), 55),
                "priority_reason": enriched.get("priority_reason") or "Family action is concrete and tied to tomorrow after Asr.",
            }
        )
    enriched["domain"] = _safe_domain_for_text(
        enriched.get("domain"),
        " ".join([_item_text(enriched), str(raw_message or "")]),
    )
    return enriched


def _augment_items_from_raw(items: list[dict[str, Any]], raw_message: str) -> list[dict[str, Any]]:
    enriched = [_augment_item_from_raw(item, raw_message) for item in items]
    if _sleep_target(raw_message) and not any(_looks_like_sleep_item(item) for item in enriched):
        enriched.append(_augment_item_from_raw({"title": "Fix bedtime routine", "kind": "habit", "domain": "health"}, raw_message))
    if _family_call_detected(raw_message) and not any(_looks_like_family_call_item(item) for item in enriched):
        enriched.append(
            _augment_item_from_raw(
                {"title": "Call family tomorrow after Asr", "kind": "task", "domain": "family"},
                raw_message,
            )
        )
    return enriched


def _item_list_from_payload(payload: dict[str, Any], entry: IntakeEntry, raw_message: str) -> list[dict[str, Any]]:
    raw_items = payload.get("items")
    if isinstance(raw_items, list) and raw_items:
        return [item for item in raw_items if isinstance(item, dict)]

    life_item = payload.get("life_item")
    if isinstance(life_item, dict):
        merged = dict(payload)
        merged.update(life_item)
        return [merged]

    return [
        {
            "title": entry.title or raw_message,
            "summary": entry.summary,
            "domain": entry.domain,
            "kind": entry.kind,
            "status": entry.status,
            "desired_outcome": entry.desired_outcome,
            "next_action": entry.next_action,
            "priority": (entry.promotion_payload_json or {}).get("priority", "medium"),
        }
    ]


def _wiki_fact_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_facts = payload.get("wiki_facts") or payload.get("memory_facts") or []
    if not isinstance(raw_facts, list):
        return []
    return [fact for fact in raw_facts if isinstance(fact, dict)]


def _context_links_from_hits(hits) -> list[dict[str, Any]]:
    links = []
    for hit in hits[:4]:
        links.append(
            {
                "title": hit.title,
                "uri": hit.uri or hit.path,
                "path": hit.path,
                "domain": hit.domain,
                "source": hit.source,
                "score": hit.score,
            }
        )
    return links


def _score_item(item: dict[str, Any], *, context_links: list[dict[str, Any]], now_utc: datetime) -> tuple[int, dict[str, Any], str]:
    explicit = _coerce_score(item.get("priority_score"))
    priority_label = str(item.get("priority") or "medium").strip().lower()
    score = explicit if explicit is not None else BASE_SCORE.get(priority_label, 52)
    factors: dict[str, Any] = {"base": score, "signals": []}

    due_at = _coerce_due_at(item.get("due_at"))
    if due_at:
        due_utc = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
        due_utc = due_utc.astimezone(timezone.utc)
        if due_utc <= now_utc + timedelta(hours=24):
            score += 30
            factors["signals"].append("deadline_24h")
        elif due_utc <= now_utc + timedelta(days=3):
            score += 22
            factors["signals"].append("deadline_3d")
        else:
            score += 12
            factors["signals"].append("deadline")

    text = " ".join(str(item.get(key) or "") for key in ("title", "summary", "desired_outcome", "next_action")).lower()
    domain = _safe_domain_for_text(item.get("domain"), text)
    if domain in {"deen", "family", "health"}:
        score += 8
        factors["signals"].append(f"life_anchor:{domain}")
    if any(token in text for token in ("urgent", "today", "deadline", "promised", "owe", "invoice")):
        score += 12
        factors["signals"].append("explicit_pressure")
    if context_links:
        score += min(12, 4 * len(context_links))
        factors["signals"].append("wiki_context_match")
    if _safe_kind(item.get("kind")) in {"commitment", "task"}:
        score += 5
        factors["signals"].append("actionable")

    score = max(0, min(100, int(score)))
    factors["final"] = score
    reason = _clean(item.get("priority_reason"), limit=500)
    if not reason:
        signals = ", ".join(factors["signals"][:4]) or "default life-system ranking"
        reason = f"Priority {score}/100 from {signals}."
    return score, factors, reason


async def _get_intake_agent() -> Agent | None:
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == "intake-inbox"))
        return result.scalar_one_or_none()


async def _make_or_update_entry(
    *,
    base_entry: IntakeEntry,
    raw_message: str,
    item: dict[str, Any],
    index: int,
) -> IntakeEntry:
    async with async_session() as db:
        entry = await db.get(IntakeEntry, base_entry.id) if index == 0 else None
        if entry is None:
            entry = IntakeEntry(
                source=base_entry.source,
                source_agent=base_entry.source_agent,
                source_session_id=base_entry.source_session_id,
                raw_text=raw_message,
            )
            db.add(entry)

        entry.title = _clean(item.get("title"), limit=300) or _clean(raw_message, limit=300) or "Captured life input"
        entry.summary = _clean(item.get("summary"), limit=1000)
        entry.domain = _safe_domain_for_text(item.get("domain"), _item_text(item))
        entry.kind = _safe_kind(item.get("kind"))
        entry.status = _safe_status(item.get("status"))
        entry.desired_outcome = _clean(item.get("desired_outcome"), limit=1000)
        entry.next_action = _clean(item.get("next_action"), limit=1000)
        questions = item.get("follow_up_questions") if isinstance(item.get("follow_up_questions"), list) else []
        entry.follow_up_questions_json = [str(q).strip() for q in questions if str(q).strip()][:3]
        entry.structured_data_json = dict(item)
        await db.commit()
        await db.refresh(entry)
        return entry


async def _attach_priority_payload(entry: IntakeEntry, item: dict[str, Any], payload: dict[str, Any]) -> IntakeEntry:
    async with async_session() as db:
        row = await db.get(IntakeEntry, entry.id)
        if not row:
            return entry
        row.promotion_payload_json = payload
        row.next_action = _clean(item.get("next_action")) or row.next_action
        await db.commit()
        await db.refresh(row)
        return row


async def _create_wiki_proposals(*, payload: dict[str, Any], session_id: int | None) -> list:
    proposals = []
    for fact in _wiki_fact_list(payload)[:5]:
        title = _clean(fact.get("title"), limit=200)
        content = _clean(fact.get("content") or fact.get("summary"), limit=4000)
        if not title or not content:
            continue
        domain = _safe_domain(fact.get("domain"))
        target_path = classify_note_path(scope="shared_domain", domain=domain, agent_name="wiki-curator", title=title)
        async with async_session() as db:
            existing = await db.scalar(
                select(SharedMemoryProposal.id)
                .where(
                    SharedMemoryProposal.target_path == str(target_path),
                    SharedMemoryProposal.status == "pending",
                )
                .limit(1)
            )
        if existing:
            continue
        try:
            proposals.append(
                await create_shared_memory_review_proposal(
                    SharedMemoryPromoteRequest(
                        agent_name="wiki-curator",
                        title=title,
                        content=content,
                        scope="shared_domain",
                        domain=domain,
                        session_id=session_id,
                        source_uri=f"lifeos://intake-session/{session_id}" if session_id else "lifeos://intake",
                        tags=["lifeos", "shared-memory", "raw-input"],
                        confidence=str(fact.get("confidence") or "medium"),
                    )
                )
            )
        except Exception:
            continue
    return proposals


async def synthesize_intake_capture(*, raw_message: str, primary_entry: IntakeEntry | None) -> dict[str, Any]:
    if not primary_entry:
        return {"entries": [], "life_items": [], "wiki_proposals": [], "auto_promoted_count": 0}

    agent = await _get_intake_agent()
    payload = dict(primary_entry.structured_data_json or {})
    items = _augment_items_from_raw(_item_list_from_payload(payload, primary_entry, raw_message), raw_message)
    entries: list[IntakeEntry] = []
    life_items: list[LifeItem] = []
    now_utc = datetime.now(timezone.utc)

    for index, item in enumerate(items[:8]):
        inferred_due_at = _infer_due_at(raw_message, item, now_utc=now_utc)
        if inferred_due_at and not item.get("due_at"):
            item = {**item, "due_at": inferred_due_at.isoformat()}
        entry = await _make_or_update_entry(base_entry=primary_entry, raw_message=raw_message, item=item, index=index)
        query = " ".join(
            str(item.get(key) or "")
            for key in ("title", "summary", "desired_outcome", "next_action", "domain")
            if item.get(key)
        ) or raw_message
        hits = []
        if agent:
            try:
                hits = await search_shared_memory(query=query, agent=agent, domain=_safe_domain(item.get("domain")))
            except Exception:
                hits = []
        context_links = _context_links_from_hits(hits)
        score, factors, reason = _score_item(item, context_links=context_links, now_utc=now_utc)
        promotion_payload = {
            "title": entry.title,
            "kind": entry.kind,
            "domain": entry.domain,
            "priority": _priority_from_score(score),
            "notes": item.get("notes"),
            "next_action": entry.next_action,
            "due_at": _coerce_due_at(item.get("due_at")),
            "start_date": item.get("start_date"),
            "recurrence_rule": item.get("recurrence_rule"),
            "priority_score": score,
            "priority_reason": reason,
            "priority_factors": factors,
            "context_links": context_links,
            "last_prioritized_at": now_utc.replace(tzinfo=None).isoformat(),
        }
        due_at_value = promotion_payload["due_at"]
        if isinstance(due_at_value, datetime):
            promotion_payload["due_at"] = due_at_value.isoformat()
        entry = await _attach_priority_payload(entry, item, promotion_payload)
        entries.append(entry)

        clear = entry.status == "ready" and entry.kind in PROMOTABLE_KINDS and not entry.follow_up_questions_json
        if clear and not entry.linked_life_item_id:
            promoted_entry, life_item = await promote_intake_entry(entry.id)
            if promoted_entry:
                entries[-1] = promoted_entry
            if life_item:
                life_items.append(life_item)

    proposals = await _create_wiki_proposals(payload=payload, session_id=primary_entry.source_session_id)
    return {
        "entries": entries,
        "life_items": life_items,
        "wiki_proposals": proposals,
        "auto_promoted_count": len(life_items),
    }
