"""Memory service - manages agent conversation context and retention."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable, Any

from sqlalchemy import delete, func, select

from app.database import async_session
from app.models import AuditLog, MemoryEntry
from app.services.events import publish_event
from app.services.system_settings import get_data_start_date

logger = logging.getLogger(__name__)

_SUMMARY_PREFIX = "[SUMMARY]\n"


async def get_context(
    agent_name: str,
    limit: int = 20,
    session_id: int | None = None,
    apply_data_start_filter: bool = False,
) -> list[dict]:
    """Return the recent conversation context for an agent as a list of message dicts.

    If *session_id* is given and a summary MemoryEntry exists for that session,
    it is prepended as a system message so the LLM has prior context.
    """
    cutoff_dt = None
    if apply_data_start_filter:
        data_start = await get_data_start_date()
        cutoff_dt = datetime.combine(data_start, datetime.min.time()).replace(tzinfo=None)
    async with async_session() as db:
        # Check for a summary entry first (role="summary")
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

        # Build conditions list then apply in one .where() call for clarity.
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

        messages: list[dict] = []
        if summary_entry:
            # Prepend summary as a system message so the LLM sees prior context
            messages.append({"role": "system", "content": summary_entry.content})
        messages.extend({"role": entry.role, "content": entry.content} for entry in entries)
        return messages


async def save_message(agent_name: str, role: str, content: str, session_id: int | None = None):
    """Persist a single message to the memory store and emit a realtime event."""
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


async def clear_memory(agent_name: str, session_id: int | None = None):
    """Delete all memory entries for an agent, optionally scoped to a session.

    When *session_id* is None **only session-less (global) memory** is deleted;
    session-scoped entries are left intact.
    """
    async with async_session() as db:
        conditions = [MemoryEntry.agent_name == agent_name]
        if session_id is not None:
            conditions.append(MemoryEntry.session_id == session_id)
        else:
            conditions.append(MemoryEntry.session_id.is_(None))
        # Single bulk DELETE — avoids loading every row into memory.
        await db.execute(delete(MemoryEntry).where(*conditions))
        await db.commit()


async def prune_old_data(memory_days: int, audit_days: int) -> dict:
    """Prune old memory and audit rows based on retention settings."""
    memory_cutoff = datetime.now(timezone.utc) - timedelta(days=memory_days)
    audit_cutoff = datetime.now(timezone.utc) - timedelta(days=audit_days)

    async with async_session() as db:
        memory_result = await db.execute(
            delete(MemoryEntry).where(MemoryEntry.timestamp < memory_cutoff)
        )
        audit_result = await db.execute(delete(AuditLog).where(AuditLog.timestamp < audit_cutoff))
        await db.commit()
        return {
            "memory_deleted": memory_result.rowcount or 0,
            "audit_deleted": audit_result.rowcount or 0,
        }


async def summarise_session(
    agent_name: str,
    session_id: int,
    llm_call: Callable[..., Awaitable[Any]],
    threshold: int = 30,
) -> bool:
    """Compress a long session into a single [SUMMARY] MemoryEntry.

    Returns True if summarisation was performed, False if the session is short
    enough that no action was needed.

    The *llm_call* argument must be an async callable matching the signature
    of ``app.services.llm.chat_completion``:
        await llm_call(messages, provider, model, ...)
    """
    async with async_session() as db:
        # Count non-summary entries for this session
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

        # Fetch the last 40 messages for summarisation context
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

    # Build the summarisation prompt outside the DB session
    conversation_text = "\n".join(
        f"{e.role.upper()}: {e.content}" for e in recent
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
        logger.exception("summarise_session: LLM call failed for %s/%s – skipping", agent_name, session_id)
        return False

    # Write the summary and delete non-summary rows in a new DB session
    async with async_session() as db:
        await db.execute(
            delete(MemoryEntry).where(
                MemoryEntry.agent_name == agent_name,
                MemoryEntry.session_id == session_id,
                MemoryEntry.role != "summary",
            )
        )
        # Remove any stale summary entries too
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
