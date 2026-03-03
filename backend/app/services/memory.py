"""Memory service - manages agent conversation context and retention."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import async_session
from app.models import AuditLog, MemoryEntry
from app.services.system_settings import get_data_start_date


async def get_context(
    agent_name: str,
    limit: int = 20,
    session_id: int | None = None,
    apply_data_start_filter: bool = False,
) -> list[dict]:
    cutoff_dt = None
    if apply_data_start_filter:
        data_start = await get_data_start_date()
        cutoff_dt = datetime.combine(data_start, datetime.min.time()).replace(tzinfo=None)
    async with async_session() as db:
        query = (
            select(MemoryEntry)
            .where(MemoryEntry.agent_name == agent_name)
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
        )
        if cutoff_dt:
            query = query.where(MemoryEntry.timestamp >= cutoff_dt)
        if session_id is None:
            query = query.where(MemoryEntry.session_id.is_(None))
        else:
            query = query.where(MemoryEntry.session_id == session_id)
        result = await db.execute(query)
        entries = list(result.scalars().all())
        entries.reverse()
        return [{"role": entry.role, "content": entry.content} for entry in entries]


async def save_message(agent_name: str, role: str, content: str, session_id: int | None = None):
    async with async_session() as db:
        entry = MemoryEntry(agent_name=agent_name, role=role, content=content, session_id=session_id)
        db.add(entry)
        await db.commit()


async def clear_memory(agent_name: str, session_id: int | None = None):
    async with async_session() as db:
        query = select(MemoryEntry).where(MemoryEntry.agent_name == agent_name)
        if session_id is not None:
            query = query.where(MemoryEntry.session_id == session_id)
        result = await db.execute(query)
        for entry in result.scalars().all():
            await db.delete(entry)
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
