"""Voice session lifecycle management (single active session policy)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.database import async_session
from app.models import VoiceSession


def _session_key(guild_id: str, channel_id: str) -> str:
    return f"{guild_id}:{channel_id}"


async def start_voice_session(
    guild_id: str,
    channel_id: str,
    agent_name: str,
    queue_policy: str = "replace",
) -> VoiceSession:
    async with async_session() as db:
        active = await db.execute(select(VoiceSession).where(VoiceSession.status == "active"))
        existing_active = active.scalar_one_or_none()
        if existing_active and existing_active.session_key != _session_key(guild_id, channel_id):
            raise HTTPException(status_code=409, detail="Another active voice session exists")

        result = await db.execute(
            select(VoiceSession).where(VoiceSession.session_key == _session_key(guild_id, channel_id))
        )
        row = result.scalar_one_or_none()
        if row:
            row.status = "active"
            row.agent_name = agent_name
            row.queue_policy = queue_policy
            row.generation += 1
            row.ended_at = None
        else:
            row = VoiceSession(
                guild_id=guild_id,
                channel_id=channel_id,
                session_key=_session_key(guild_id, channel_id),
                agent_name=agent_name,
                status="active",
                generation=1,
                queue_policy=queue_policy,
            )
            db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def interrupt_voice_session(session_id: int) -> VoiceSession:
    async with async_session() as db:
        result = await db.execute(select(VoiceSession).where(VoiceSession.id == session_id))
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Voice session not found")
        row.generation += 1
        await db.commit()
        await db.refresh(row)
        return row


async def stop_voice_session(session_id: int) -> VoiceSession:
    async with async_session() as db:
        result = await db.execute(select(VoiceSession).where(VoiceSession.id == session_id))
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Voice session not found")
        row.status = "stopped"
        row.ended_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
        return row


async def clear_all_voice_sessions() -> None:
    async with async_session() as db:
        await db.execute(delete(VoiceSession))
        await db.commit()
