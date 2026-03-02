"""Memory service - manages agent conversation context and retention."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import async_session
from app.models import AuditLog, MemoryEntry


async def get_context(agent_name: str, limit: int = 20) -> list[dict]:
    async with async_session() as db:
        result = await db.execute(
            select(MemoryEntry)
            .where(MemoryEntry.agent_name == agent_name)
            .order_by(MemoryEntry.timestamp.desc())
            .limit(limit)
        )
        entries = list(result.scalars().all())
        entries.reverse()
        return [{"role": entry.role, "content": entry.content} for entry in entries]


async def save_message(agent_name: str, role: str, content: str):
    async with async_session() as db:
        entry = MemoryEntry(agent_name=agent_name, role=role, content=content)
        db.add(entry)
        await db.commit()


async def clear_memory(agent_name: str):
    async with async_session() as db:
        result = await db.execute(select(MemoryEntry).where(MemoryEntry.agent_name == agent_name))
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
