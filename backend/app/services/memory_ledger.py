"""Private durable memory ledger for user-authored facts and actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

from app.database import async_session
from app.models import Agent, IntakeEntry, LifeItem, MemoryEvent
from app.services.vault import (
    obsidian_private_root,
    obsidian_vault_enabled,
    slugify_note,
    vault_note_uri,
)

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'’-]{2,}")
_QUESTION_ONLY_RE = re.compile(r"^\s*(what|how|why|when|where|who|which|can|could|should|would|is|are|do|does)\b", re.I)
_USER_FACT_RE = re.compile(
    r"\b("
    r"i\s+(?:am|was|will|did|do|have|had|need|want|ate|drank|slept|woke|sent|made|prepared|finished|completed|bought|started|stopped)|"
    r"my\s+|remind\s+me|remember\s+|note\s+that|capture\s+|todo\s+|task\s+"
    r")\b",
    re.I,
)
_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "work": ("hr", "work", "invoice", "tax", "paper", "request", "workday", "job", "client", "repo", "deploy"),
    "health": ("sleep", "meal", "protein", "water", "hydration", "training", "workout", "bed", "wake"),
    "deen": ("prayer", "dhuhr", "asr", "maghrib", "isha", "fajr", "quran", "wudu", "dhikr"),
    "family": ("mother", "mom", "wife", "family", "message", "call"),
    "planning": ("plan", "goal", "habit", "idea", "remind", "schedule"),
}


@dataclass(slots=True)
class MemoryLedgerHit:
    id: int
    title: str
    domain: str | None
    kind: str | None
    source: str
    score: float
    snippet: str
    raw_text: str
    source_agent: str | None
    source_session_id: int | None
    linked_life_item_id: int | None
    linked_intake_entry_id: int | None
    created_at: datetime | None
    uri: str | None = None


def _clean_text(value: Any, *, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip() if limit and len(text) > limit else text


def _words(text: str) -> set[str]:
    return {match.group(0).lower().strip("'’") for match in _WORD_RE.finditer(text or "")}


def _checksum(*parts: Any) -> str:
    payload = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _title_from_text(text: str, *, default: str = "Memory event") -> str:
    for line in str(text or "").splitlines():
        cleaned = line.strip(" #-*\t")
        if len(cleaned) >= 4:
            return cleaned[:120]
    return default


def _infer_domain(text: str, fallback: str | None = None) -> str | None:
    lowered = str(text or "").lower()
    for domain, hints in _DOMAIN_HINTS.items():
        if any(hint in lowered for hint in hints):
            return domain
    return fallback


def _infer_kind(text: str, fallback: str | None = None) -> str | None:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("ate", "meal", "breakfast", "lunch", "dinner", "protein", "water", "drank", "sleep", "woke")):
        return "daily_log"
    if any(token in lowered for token in ("remind me", "due", "deadline", "request", "send", "submit")):
        return "commitment"
    return fallback or "user_fact"


def _should_store_user_turn(text: str) -> bool:
    cleaned = _clean_text(text)
    if len(cleaned) < 8:
        return False
    if _USER_FACT_RE.search(cleaned):
        return True
    if _QUESTION_ONLY_RE.search(cleaned) and not re.search(r"\b(i|my|me)\b", cleaned, re.I):
        return False
    return False


def _extract_entities(text: str) -> list[str]:
    entities: list[str] = []
    for pattern in [
        r"\bHR\b",
        r"\bCNSS\b",
        r"\bDGI\b",
        r"\bWorkday\b",
        r"\bCasablanca\b",
    ]:
        for match in re.finditer(pattern, text or "", re.I):
            value = match.group(0)
            if value not in entities:
                entities.append(value)
    return entities[:12]


def _render_event_note(event: MemoryEvent) -> str:
    tags = event.tags_json or []
    entities = event.entities_json or []
    created = event.created_at or datetime.now(timezone.utc)
    return (
        "---\n"
        f"id: memory-event-{event.id}\n"
        "scope: private\n"
        f"domain: {event.domain or 'planning'}\n"
        f"kind: {event.kind or event.event_type}\n"
        f"source: {event.source}\n"
        f"source_agent: {event.source_agent or ''}\n"
        f"source_session_id: {event.source_session_id or ''}\n"
        f"linked_life_item_id: {event.linked_life_item_id or ''}\n"
        f"linked_intake_entry_id: {event.linked_intake_entry_id or ''}\n"
        f"created_at: {created.isoformat()}\n"
        "tags:\n"
        + "".join(f"  - {tag}\n" for tag in tags)
        + "---\n\n"
        f"# {event.title}\n\n"
        f"Summary: {event.summary or event.title}\n\n"
        "Raw:\n\n"
        f"{event.raw_text.strip()}\n\n"
        + (f"Entities: {', '.join(entities)}\n" if entities else "")
    )


def _write_private_timeline_note(event: MemoryEvent) -> str | None:
    if not obsidian_vault_enabled():
        return None
    created = event.created_at or datetime.now(timezone.utc)
    root = obsidian_private_root() / "life-timeline" / f"{created:%Y-%m-%d}"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{event.id:06d}-{slugify_note(event.title, default='memory-event')}.md"
    path.write_text(_render_event_note(event), encoding="utf-8")
    return vault_note_uri(path)


async def record_memory_event(
    *,
    raw_text: str,
    source: str = "api",
    source_agent: str | None = None,
    source_session_id: int | None = None,
    event_type: str = "user_fact",
    domain: str | None = None,
    kind: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    tags: list[str] | None = None,
    entities: list[str] | None = None,
    linked_life_item_id: int | None = None,
    linked_intake_entry_id: int | None = None,
    linked_job_id: int | None = None,
    source_uri: str | None = None,
) -> MemoryEvent:
    clean_raw = str(raw_text or "").strip()
    if not clean_raw:
        raise ValueError("raw_text is required")
    inferred_domain = _infer_domain(clean_raw, domain)
    inferred_kind = _infer_kind(clean_raw, kind)
    clean_title = _clean_text(title or _title_from_text(clean_raw), limit=300)
    clean_summary = _clean_text(summary or clean_title, limit=1000)
    event_checksum = _checksum(source, source_agent, source_session_id, event_type, clean_raw, linked_life_item_id, linked_intake_entry_id)
    tag_values = list(dict.fromkeys([*(tags or []), "lifeos", "memory-ledger"]))
    entity_values = list(dict.fromkeys([*(entities or []), *_extract_entities(clean_raw)]))[:20]

    async with async_session() as db:
        existing = await db.execute(select(MemoryEvent).where(MemoryEvent.checksum == event_checksum).limit(1))
        row = existing.scalar_one_or_none()
        if row:
            return row
        row = MemoryEvent(
            source=source,
            source_agent=source_agent,
            source_session_id=source_session_id,
            event_type=event_type,
            domain=inferred_domain,
            kind=inferred_kind,
            title=clean_title,
            summary=clean_summary,
            raw_text=clean_raw,
            tags_json=tag_values,
            entities_json=entity_values,
            linked_life_item_id=linked_life_item_id,
            linked_intake_entry_id=linked_intake_entry_id,
            linked_job_id=linked_job_id,
            source_uri=source_uri,
            checksum=event_checksum,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        uri = _write_private_timeline_note(row)
        if uri and row.source_uri != uri:
            row.source_uri = uri
            await db.commit()
            await db.refresh(row)
        return row


async def maybe_record_user_turn(
    *,
    user_message: str,
    agent_name: str,
    session_id: int | None,
    source: str,
) -> MemoryEvent | None:
    if not _should_store_user_turn(user_message):
        return None
    return await record_memory_event(
        raw_text=user_message,
        source=source,
        source_agent=agent_name,
        source_session_id=session_id,
        event_type="user_turn",
        tags=["chat"],
    )


async def record_capture_memory(
    *,
    raw_text: str,
    source: str,
    source_agent: str | None,
    source_session_id: int | None,
    entry: IntakeEntry | None = None,
    life_item: LifeItem | None = None,
    event_type: str = "capture",
) -> MemoryEvent | None:
    if not raw_text.strip():
        return None
    title = (life_item.title if life_item else None) or (entry.title if entry else None) or _title_from_text(raw_text)
    summary = (entry.summary if entry else None) or title
    memory_raw_text = raw_text
    if life_item and life_item.due_at:
        due_utc = life_item.due_at
        if due_utc.tzinfo is None:
            due_utc = due_utc.replace(tzinfo=timezone.utc)
        else:
            due_utc = due_utc.astimezone(timezone.utc)
        memory_raw_text = f"{raw_text.rstrip()}\n\nTracked deadline UTC: {due_utc.isoformat()}"
    return await record_memory_event(
        raw_text=memory_raw_text,
        source=source,
        source_agent=source_agent,
        source_session_id=source_session_id,
        event_type=event_type,
        domain=(life_item.domain if life_item else None) or (entry.domain if entry else None),
        kind=(life_item.kind if life_item else None) or (entry.kind if entry else None),
        title=title,
        summary=summary,
        tags=[event_type],
        linked_life_item_id=life_item.id if life_item else (entry.linked_life_item_id if entry else None),
        linked_intake_entry_id=entry.id if entry else None,
    )


async def record_daily_log_memory(
    *,
    raw_logs: list[dict[str, Any]],
    result_text: str,
    source_agent: str | None,
    source: str,
) -> MemoryEvent | None:
    if not raw_logs:
        return None
    parts = [f"{log.get('kind')}: {json.dumps(log, ensure_ascii=True, sort_keys=True)}" for log in raw_logs]
    raw_text = "Daily log applied.\n" + "\n".join(parts)
    return await record_memory_event(
        raw_text=raw_text,
        source=source,
        source_agent=source_agent,
        event_type="daily_log",
        domain="health",
        kind="daily_log",
        title="Daily log applied",
        summary=result_text[:1000],
        tags=["daily-log", "scorecard"],
    )


def _hit_from_row(row: MemoryEvent, *, query_words: set[str]) -> MemoryLedgerHit:
    text = f"{row.title} {row.summary or ''} {row.raw_text}"
    words = _words(text)
    overlap = len(words & query_words)
    score = float(overlap * 10 + min(len(row.raw_text), 500) / 500)
    snippet = _clean_text(row.raw_text, limit=700)
    return MemoryLedgerHit(
        id=row.id,
        title=row.title,
        domain=row.domain,
        kind=row.kind,
        source=row.source,
        score=score,
        snippet=snippet,
        raw_text=row.raw_text,
        source_agent=row.source_agent,
        source_session_id=row.source_session_id,
        linked_life_item_id=row.linked_life_item_id,
        linked_intake_entry_id=row.linked_intake_entry_id,
        created_at=row.created_at,
        uri=row.source_uri,
    )


async def search_memory_events(
    *,
    query: str,
    agent: Agent | Any | None = None,
    domain: str | None = None,
    limit: int = 6,
) -> list[MemoryLedgerHit]:
    query_words = _words(query)
    if not query_words:
        return []
    domain_filter = domain
    if domain_filter is None and agent is not None:
        shared_domains = list(getattr(agent, "shared_domains", []) or [])
        if len(shared_domains) == 1:
            domain_filter = str(shared_domains[0])
    clauses = []
    for word in sorted(query_words, key=len, reverse=True)[:8]:
        like = f"%{word}%"
        clauses.append(MemoryEvent.title.ilike(like))
        clauses.append(MemoryEvent.summary.ilike(like))
        clauses.append(MemoryEvent.raw_text.ilike(like))
    async with async_session() as db:
        stmt = (
            select(MemoryEvent)
            .where(MemoryEvent.status == "active")
            .where(or_(*clauses))
            .order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc())
            .limit(80)
        )
        if domain_filter:
            stmt = stmt.where(or_(MemoryEvent.domain == domain_filter, MemoryEvent.domain.is_(None)))
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
    hits = [_hit_from_row(row, query_words=query_words) for row in rows]
    hits.sort(key=lambda hit: (hit.score, (hit.created_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp()), reverse=True)
    return hits[: max(1, min(limit, 20))]


async def list_private_memory_events(*, status: str | None = "active", limit: int = 100) -> list[MemoryEvent]:
    async with async_session() as db:
        stmt = select(MemoryEvent).order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc()).limit(max(1, min(limit, 200)))
        if status:
            stmt = stmt.where(MemoryEvent.status == status)
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def set_private_memory_event_status(event_id: int, status: str) -> MemoryEvent:
    if status not in {"active", "archived", "deleted"}:
        raise ValueError("Invalid memory status")
    async with async_session() as db:
        row = await db.get(MemoryEvent, event_id)
        if not row:
            raise ValueError("Memory event not found")
        row.status = status
        await db.commit()
        await db.refresh(row)
        return row


def render_memory_ledger_context(hits: list[MemoryLedgerHit]) -> str:
    if not hits:
        return ""
    lines = ["[PRIVATE MEMORY LEDGER]", "User-authored durable facts/actions. Prefer these for prior user details."]
    for hit in hits:
        created = hit.created_at.isoformat() if hit.created_at else "unknown"
        lines.append(
            f"- #{hit.id} {hit.title} ({hit.domain or 'general'}/{hit.kind or 'fact'}, {created})\n"
            f"  Source: {hit.source}; session: {hit.source_session_id or 'n/a'}; linked life item: {hit.linked_life_item_id or 'n/a'}\n"
            f"  Raw: {hit.snippet}"
        )
    lines.append("[END PRIVATE MEMORY LEDGER]")
    return "\n".join(lines)
