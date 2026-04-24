"""Raw life input synthesis into connected priorities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import Agent, IntakeEntry, LifeItem, SharedMemoryPromoteRequest
from app.services.intake import promote_intake_entry
from app.services.shared_memory import create_shared_memory_review_proposal, search_shared_memory

VALID_DOMAINS = {"deen", "family", "work", "health", "planning"}
VALID_KINDS = {"idea", "task", "goal", "habit", "commitment", "routine", "note"}
PROMOTABLE_KINDS = {"task", "goal", "habit", "commitment", "routine"}
PRIORITY_BY_SCORE = ((75, "high"), (40, "medium"), (0, "low"))
BASE_SCORE = {"high": 78, "medium": 52, "low": 25}


def _clean(value: Any, *, limit: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _safe_domain(value: Any) -> str:
    candidate = str(value or "planning").strip().lower()
    return candidate if candidate in VALID_DOMAINS else "planning"


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

    domain = _safe_domain(item.get("domain"))
    text = " ".join(str(item.get(key) or "") for key in ("title", "summary", "desired_outcome", "next_action")).lower()
    if domain in {"deen", "family", "health"}:
        score += 8
        factors["signals"].append(f"life_anchor:{domain}")
    if any(token in text for token in ("urgent", "today", "tomorrow", "deadline", "promised", "owe", "invoice")):
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
        entry.domain = _safe_domain(item.get("domain"))
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
        try:
            proposals.append(
                await create_shared_memory_review_proposal(
                    SharedMemoryPromoteRequest(
                        agent_name="wiki-curator",
                        title=title,
                        content=content,
                        scope="shared_domain",
                        domain=_safe_domain(fact.get("domain")),
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
    items = _item_list_from_payload(payload, primary_entry, raw_message)
    entries: list[IntakeEntry] = []
    life_items: list[LifeItem] = []
    now_utc = datetime.now(timezone.utc)

    for index, item in enumerate(items[:8]):
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
