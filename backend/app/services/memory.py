"""Memory service abstraction for SQLite and OpenViking backends."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, func, select

from app.config import settings
from app.database import async_session
from app.models import AuditLog, MemoryEntry
from app.services.events import publish_event
from app.services.openviking_client import (
    OpenVikingApiError,
    OpenVikingUnavailableError,
    build_session_root_uri,
    openviking_client,
)
from app.services.system_settings import get_data_start_date

logger = logging.getLogger(__name__)

_SUMMARY_PREFIX = "[SUMMARY]\n"
_COMMIT_IN_PROGRESS_PATTERN = re.compile(r"commit in progress", re.IGNORECASE)


def _use_openviking() -> bool:
    return settings.openviking_enabled and settings.normalized_memory_backend == "openviking"


def _session_scope(session_id: int | None) -> int | str:
    return session_id if session_id is not None else "global"


def _parse_openviking_timestamp(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    normalized = str(raw).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _message_content(payload: dict[str, Any]) -> str:
    for part in payload.get("parts") or []:
        if part.get("type") == "text":
            return str(part.get("text") or "")
    return ""


def _normalize_summary_content(content: str) -> str:
    stripped = str(content or "").strip()
    if not stripped:
        return ""
    return stripped if stripped.startswith(_SUMMARY_PREFIX) else f"{_SUMMARY_PREFIX}{stripped}"


def _openviking_matches_memory_row(payload: dict[str, Any], row: MemoryEntry) -> bool:
    return (payload.get("role") or "assistant") == row.role and _message_content(payload) == row.content


def _wrap_openviking_error(operation: str, agent_name: str, session_id: int | None, exc: Exception) -> OpenVikingUnavailableError:
    return OpenVikingUnavailableError(
        f"OpenViking {operation} failed for agent '{agent_name}' session '{_session_scope(session_id)}': {exc}"
    )


def _is_commit_in_progress_error(exc: Exception) -> bool:
    return bool(_COMMIT_IN_PROGRESS_PATTERN.search(str(exc)))


async def _commit_openviking_session(agent_name: str, session_id: int | str) -> None:
    for attempt in range(2):
        try:
            await openviking_client.commit_session(agent_name, session_id, wait=False)
            return
        except Exception as exc:
            if not _is_commit_in_progress_error(exc):
                raise
            if attempt == 0:
                logger.warning(
                    "OpenViking commit already in progress for %s/%s; retrying once",
                    agent_name,
                    session_id,
                )
                await asyncio.sleep(0.25)
                continue
            logger.warning(
                "OpenViking commit still in progress for %s/%s after retry; leaving appended message as-is",
                agent_name,
                session_id,
            )
            return


async def _openviking_summary_message(
    agent_name: str,
    session_id: int | None,
) -> dict[str, str] | None:
    content = await openviking_client.read_session_summary(agent_name, _session_scope(session_id))
    normalized = _normalize_summary_content(content)
    if not normalized:
        return None
    return {"role": "system", "content": normalized}


async def _openviking_messages(
    agent_name: str,
    session_id: int | None,
    *,
    limit: int = 200,
    apply_data_start_filter: bool = False,
) -> list[dict[str, Any]]:
    cutoff_dt = None
    if apply_data_start_filter:
        data_start = await get_data_start_date()
        cutoff_dt = datetime.combine(data_start, datetime.min.time()).replace(tzinfo=timezone.utc)

    messages = await openviking_client.read_session_messages(agent_name, _session_scope(session_id))
    normalized: list[dict[str, Any]] = []
    for payload in messages:
        timestamp = _parse_openviking_timestamp(payload.get("created_at"))
        if cutoff_dt and timestamp < cutoff_dt:
            continue
        normalized.append(
            {
                "id": str(payload.get("id") or ""),
                "role": payload.get("role") or "assistant",
                "content": _message_content(payload),
                "timestamp": timestamp,
            }
        )
    if limit and limit > 0:
        return normalized[-max(1, limit):]
    return normalized


async def _sqlite_get_context(
    agent_name: str,
    limit: int = 20,
    session_id: int | None = None,
    apply_data_start_filter: bool = False,
) -> list[dict[str, Any]]:
    cutoff_dt = None
    if apply_data_start_filter:
        data_start = await get_data_start_date()
        cutoff_dt = datetime.combine(data_start, datetime.min.time()).replace(tzinfo=None)
    async with async_session() as db:
        summary_entry: MemoryEntry | None = None
        if session_id is not None:
            summary_q = (
                select(MemoryEntry)
                .where(
                    MemoryEntry.agent_name == agent_name,
                    MemoryEntry.session_id == session_id,
                    MemoryEntry.role == "summary",
                )
                .order_by(MemoryEntry.timestamp.desc())
                .limit(1)
            )
            summary_result = await db.execute(summary_q)
            summary_entry = summary_result.scalar_one_or_none()

        conditions = [
            MemoryEntry.agent_name == agent_name,
            MemoryEntry.role != "summary",
        ]
        if session_id is None:
            conditions.append(MemoryEntry.session_id.is_(None))
        else:
            conditions.append(MemoryEntry.session_id == session_id)
        if cutoff_dt:
            conditions.append(MemoryEntry.timestamp >= cutoff_dt)

        query = (
            select(MemoryEntry)
            .where(*conditions)
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
        )
        result = await db.execute(query)
        entries = list(result.scalars().all())
        entries.reverse()

    messages: list[dict[str, Any]] = []
    if summary_entry:
        messages.append({"role": "system", "content": summary_entry.content})
    messages.extend({"role": entry.role, "content": entry.content} for entry in entries)
    return messages


async def _sqlite_list_session_messages(
    agent_name: str,
    session_id: int | None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    async with async_session() as db:
        conditions = [MemoryEntry.agent_name == agent_name]
        if session_id is None:
            conditions.append(MemoryEntry.session_id.is_(None))
        else:
            conditions.append(MemoryEntry.session_id == session_id)
        query = (
            select(MemoryEntry)
            .where(*conditions)
            .order_by(MemoryEntry.timestamp.asc(), MemoryEntry.id.asc())
        )
        if limit and limit > 0:
            query = query.limit(max(1, min(limit, 2000)))
        result = await db.execute(query)
        rows = list(result.scalars().all())
    return [
        {
            "id": str(row.id),
            "role": row.role,
            "content": row.content,
            "timestamp": row.timestamp,
        }
        for row in rows
    ]


async def _sqlite_save_message(agent_name: str, role: str, content: str, session_id: int | None = None) -> None:
    async with async_session() as db:
        entry = MemoryEntry(agent_name=agent_name, role=role, content=content, session_id=session_id)
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
    if session_id is not None:
        await publish_event(
            "agents.messages.appended",
            {"kind": "chat_session", "id": str(session_id)},
            {"agent_name": agent_name, "session_id": session_id, "message_id": entry.id, "role": role},
        )


async def _sqlite_clear_memory(agent_name: str, session_id: int | None = None) -> None:
    async with async_session() as db:
        conditions = [MemoryEntry.agent_name == agent_name]
        if session_id is not None:
            conditions.append(MemoryEntry.session_id == session_id)
        else:
            conditions.append(MemoryEntry.session_id.is_(None))
        await db.execute(delete(MemoryEntry).where(*conditions))
        await db.commit()


async def get_context(
    agent_name: str,
    limit: int = 20,
    session_id: int | None = None,
    apply_data_start_filter: bool = False,
) -> list[dict[str, str]]:
    """Return recent conversation context for an agent."""
    if _use_openviking():
        try:
            summary_message = await _openviking_summary_message(agent_name, session_id)
            rows = await _openviking_messages(
                agent_name,
                session_id,
                limit=limit,
                apply_data_start_filter=apply_data_start_filter,
            )
        except Exception as exc:
            raise _wrap_openviking_error("get_context", agent_name, session_id, exc) from exc
        messages: list[dict[str, str]] = []
        if summary_message:
            messages.append(summary_message)
        messages.extend({"role": row["role"], "content": row["content"]} for row in rows)
        return messages
    return await _sqlite_get_context(
        agent_name,
        limit=limit,
        session_id=session_id,
        apply_data_start_filter=apply_data_start_filter,
    )


async def list_session_messages(
    agent_name: str,
    session_id: int | None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if _use_openviking():
        try:
            return await _openviking_messages(agent_name, session_id, limit=limit)
        except Exception as exc:
            raise _wrap_openviking_error("list_session_messages", agent_name, session_id, exc) from exc
    return await _sqlite_list_session_messages(agent_name, session_id, limit=limit)


async def save_message(agent_name: str, role: str, content: str, session_id: int | None = None) -> None:
    """Persist a single message to the active memory backend."""
    if not content:
        logger.warning("save_message skipped for agent=%s role=%s: content is empty/None", agent_name, role)
        return

    if _use_openviking():
        try:
            session_scope = _session_scope(session_id)
            await openviking_client.add_message(agent_name, session_scope, role, content)
            if role == "assistant":
                await _commit_openviking_session(agent_name, session_scope)
        except Exception as exc:
            raise _wrap_openviking_error("save_message", agent_name, session_id, exc) from exc
        if session_id is not None:
            await publish_event(
                "agents.messages.appended",
                {"kind": "chat_session", "id": str(session_id)},
                {"agent_name": agent_name, "session_id": session_id, "message_id": None, "role": role},
            )
        return
    await _sqlite_save_message(agent_name, role, content, session_id=session_id)


async def clear_memory(agent_name: str, session_id: int | None = None) -> None:
    """Clear active conversation state for an agent."""
    if _use_openviking():
        try:
            await openviking_client.rm(
                build_session_root_uri(agent_name, _session_scope(session_id)),
                recursive=True,
            )
            return
        except OpenVikingApiError as exc:
            if exc.status_code == 404 or (exc.code or "").upper() == "NOT_FOUND":
                return
            raise _wrap_openviking_error("clear_memory", agent_name, session_id, exc) from exc
        except Exception as exc:
            raise _wrap_openviking_error("clear_memory", agent_name, session_id, exc) from exc
    await _sqlite_clear_memory(agent_name, session_id=session_id)


async def restore_session_messages(
    agent_name: str,
    session_id: int | None,
    messages: list[dict[str, Any]],
) -> None:
    """Restore a previously archived session transcript into the active backend."""
    summary_content = ""
    transcript_rows: list[dict[str, Any]] = []

    for message in messages or []:
        role = str(message.get("role") or "assistant")
        content = str(message.get("content") or "")
        if not content:
            continue
        if role == "summary":
            summary_content = content
            continue
        transcript_rows.append(
            {
                "role": role,
                "content": content,
                "timestamp": _parse_openviking_timestamp(str(message.get("timestamp") or "")),
            }
        )

    if _use_openviking():
        try:
            session_scope = _session_scope(session_id)
            for row in transcript_rows:
                await openviking_client.add_message(agent_name, session_scope, row["role"], row["content"])
            if transcript_rows:
                await _commit_openviking_session(agent_name, session_scope)
            if summary_content:
                await openviking_client.write_session_summary(
                    agent_name,
                    session_scope,
                    _normalize_summary_content(summary_content),
                )
            return
        except Exception as exc:
            raise _wrap_openviking_error("restore_session_messages", agent_name, session_id, exc) from exc

    async with async_session() as db:
        for row in transcript_rows:
            db.add(
                MemoryEntry(
                    agent_name=agent_name,
                    session_id=session_id,
                    role=row["role"],
                    content=row["content"],
                    timestamp=row["timestamp"],
                )
            )
        if summary_content:
            db.add(
                MemoryEntry(
                    agent_name=agent_name,
                    session_id=session_id,
                    role="summary",
                    content=_normalize_summary_content(summary_content),
                    timestamp=datetime.now(timezone.utc),
                )
            )
        await db.commit()


async def prune_old_data(memory_days: int, audit_days: int) -> dict[str, int]:
    """Prune old data for the active backend."""
    audit_cutoff = datetime.now(timezone.utc) - timedelta(days=audit_days)

    async with async_session() as db:
        audit_result = await db.execute(delete(AuditLog).where(AuditLog.timestamp < audit_cutoff))
        memory_deleted = 0
        if not _use_openviking():
            memory_cutoff = datetime.now(timezone.utc) - timedelta(days=memory_days)
            memory_result = await db.execute(
                delete(MemoryEntry).where(MemoryEntry.timestamp < memory_cutoff)
            )
            memory_deleted = memory_result.rowcount or 0
        await db.commit()

    return {
        "memory_deleted": memory_deleted,
        "audit_deleted": audit_result.rowcount or 0,
    }


async def summarise_session(
    agent_name: str,
    session_id: int,
    llm_call: Callable[..., Awaitable[Any]],
    threshold: int = 30,
) -> bool:
    """Refresh a long-session summary in the active memory backend."""
    if _use_openviking():
        try:
            payloads = await openviking_client.read_session_messages(agent_name, _session_scope(session_id))
        except Exception as exc:
            raise _wrap_openviking_error("summarise_session", agent_name, session_id, exc) from exc

        if len(payloads) <= threshold:
            return False

        recent_payloads = payloads[-40:]
        conversation_text = "\n".join(
            f"{(payload.get('role') or 'assistant').upper()}: {_message_content(payload)}"
            for payload in recent_payloads
        )
        summarisation_messages = [
            {
                "role": "system",
                "content": (
                    "You are a conversation summariser. "
                    "Summarise the following conversation into 3-5 concise bullet points "
                    "that preserve the key facts, decisions, and context needed to continue the conversation. "
                    "Do NOT add interpretation; stick to what was actually said."
                ),
            },
            {"role": "user", "content": conversation_text},
        ]

        try:
            summary_text: str = await llm_call(summarisation_messages)
        except Exception:
            logger.exception("summarise_session: LLM call failed for %s/%s; skipping", agent_name, session_id)
            return False

        await openviking_client.write_session_summary(
            agent_name,
            _session_scope(session_id),
            _normalize_summary_content(summary_text),
        )
        logger.info("summarise_session: refreshed OpenViking summary for %s/%s", agent_name, session_id)
        return True

    async with async_session() as db:
        count_result = await db.execute(
            select(func.count()).where(
                MemoryEntry.agent_name == agent_name,
                MemoryEntry.session_id == session_id,
                MemoryEntry.role != "summary",
            )
        )
        count: int = count_result.scalar() or 0
        if count <= threshold:
            return False

        result = await db.execute(
            select(MemoryEntry)
            .where(
                MemoryEntry.agent_name == agent_name,
                MemoryEntry.session_id == session_id,
                MemoryEntry.role != "summary",
            )
            .order_by(MemoryEntry.timestamp.desc())
            .limit(40)
        )
        recent = list(result.scalars().all())
        recent.reverse()

    conversation_text = "\n".join(f"{entry.role.upper()}: {entry.content}" for entry in recent)
    summarisation_messages = [
        {
            "role": "system",
            "content": (
                "You are a conversation summariser. "
                "Summarise the following conversation into 3-5 concise bullet points "
                "that preserve the key facts, decisions, and context needed to continue the conversation. "
                "Do NOT add interpretation; stick to what was actually said."
            ),
        },
        {"role": "user", "content": conversation_text},
    ]

    try:
        summary_text = await llm_call(summarisation_messages)
    except Exception:
        logger.exception("summarise_session: LLM call failed for %s/%s; skipping", agent_name, session_id)
        return False

    async with async_session() as db:
        await db.execute(
            delete(MemoryEntry).where(
                MemoryEntry.agent_name == agent_name,
                MemoryEntry.session_id == session_id,
                MemoryEntry.role != "summary",
            )
        )
        await db.execute(
            delete(MemoryEntry).where(
                MemoryEntry.agent_name == agent_name,
                MemoryEntry.session_id == session_id,
                MemoryEntry.role == "summary",
            )
        )
        summary_entry = MemoryEntry(
            agent_name=agent_name,
            session_id=session_id,
            role="summary",
            content=f"{_SUMMARY_PREFIX}{summary_text}",
        )
        db.add(summary_entry)
        await db.commit()

    logger.info("summarise_session: compressed %d messages for %s/%s", count, agent_name, session_id)
    return True


async def get_legacy_memory_max_entry_id() -> int:
    async with async_session() as db:
        result = await db.execute(select(func.max(MemoryEntry.id)))
        return int(result.scalar() or 0)


async def import_legacy_memory_to_openviking() -> dict[str, int | bool]:
    """Backfill existing SQLite memory rows into OpenViking without duplicate imports."""
    if not _use_openviking():
        return {"sessions": 0, "messages": 0, "summaries": 0, "skipped_sessions": 0, "complete": True, "max_memory_entry_id": 0}

    async with async_session() as db:
        result = await db.execute(
            select(MemoryEntry).order_by(
                MemoryEntry.agent_name.asc(),
                MemoryEntry.timestamp.asc(),
                MemoryEntry.id.asc(),
            )
        )
        rows = list(result.scalars().all())

    grouped: dict[tuple[str, int | str], list[MemoryEntry]] = {}
    for row in rows:
        grouped.setdefault((row.agent_name, _session_scope(row.session_id)), []).append(row)

    imported_sessions = 0
    imported_messages = 0
    imported_summaries = 0
    skipped_sessions = 0
    max_memory_entry_id = max((row.id for row in rows), default=0)

    for (agent_name, session_scope), memory_rows in grouped.items():
        transcript_rows = [row for row in memory_rows if row.role != "summary"]
        summary_rows = [row for row in memory_rows if row.role == "summary"]
        scope_changed = False

        try:
            existing = (
                await openviking_client.read_session_messages(agent_name, session_scope)
                if transcript_rows
                else []
            )
        except Exception as exc:
            logger.warning("Skipping OpenViking import for %s/%s: %s", agent_name, session_scope, exc)
            skipped_sessions += 1
            continue

        prefix_len = 0
        compare_len = min(len(existing), len(transcript_rows))
        while prefix_len < compare_len and _openviking_matches_memory_row(existing[prefix_len], transcript_rows[prefix_len]):
            prefix_len += 1

        if prefix_len < len(existing):
            logger.warning(
                "Skipping legacy import for %s/%s because the existing OpenViking transcript diverged",
                agent_name,
                session_scope,
            )
            skipped_sessions += 1
            continue

        for row in transcript_rows[prefix_len:]:
            await openviking_client.add_message(agent_name, session_scope, row.role, row.content)
            imported_messages += 1
            scope_changed = True

        if prefix_len < len(transcript_rows):
            await openviking_client.commit_session(agent_name, session_scope, wait=True)

        if summary_rows:
            latest_summary = summary_rows[-1]
            try:
                existing_summary = await openviking_client.read_session_summary(agent_name, session_scope)
            except Exception as exc:
                logger.warning("Skipping OpenViking summary import for %s/%s: %s", agent_name, session_scope, exc)
                skipped_sessions += 1
                continue
            normalized_summary = _normalize_summary_content(latest_summary.content)
            if normalized_summary and existing_summary.strip() != normalized_summary.strip():
                await openviking_client.write_session_summary(agent_name, session_scope, normalized_summary)
                imported_summaries += 1
                scope_changed = True

        if scope_changed:
            imported_sessions += 1

    if imported_messages or imported_summaries:
        logger.info(
            "Imported %d legacy SQLite messages and %d summaries into OpenViking across %d session scopes",
            imported_messages,
            imported_summaries,
            imported_sessions,
        )
    return {
        "sessions": imported_sessions,
        "messages": imported_messages,
        "summaries": imported_summaries,
        "skipped_sessions": skipped_sessions,
        "complete": skipped_sessions == 0,
        "max_memory_entry_id": max_memory_entry_id,
    }
