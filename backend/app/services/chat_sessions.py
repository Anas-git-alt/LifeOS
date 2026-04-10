"""Chat session service with per-agent history and auto-generated titles."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.database import async_session
from app.models import ChatSession, ChatSessionArchive
from app.services.events import publish_event
from app.services.memory import clear_memory, list_session_messages, restore_session_messages

DEFAULT_SESSION_TITLE = "New chat"
MAX_TITLE_LENGTH = 160
MAX_TITLE_WORDS = 12
MAX_SEED_PROMPTS = 3
MAX_REFERENCE_MESSAGES = 8
MAX_REFERENCE_MESSAGE_CHARS = 240
SESSION_ARCHIVE_RETENTION_DAYS = 30

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "the",
    "to",
    "we",
    "what",
    "with",
    "you",
    "your",
}
_TITLE_PREFIX_PATTERN = re.compile(
    r"^(please|can you|could you|would you|help me|i need to|i want to|how do i|how can i)\s+",
    re.IGNORECASE,
)


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sanitize_title(title: str | None) -> str:
    if not title:
        return DEFAULT_SESSION_TITLE
    normalized = _collapse_spaces(title)
    if not normalized:
        return DEFAULT_SESSION_TITLE
    clipped = " ".join(normalized.split()[:MAX_TITLE_WORDS])[:MAX_TITLE_LENGTH].strip()
    return clipped or DEFAULT_SESSION_TITLE


def _normalize_prompt(text: str) -> str:
    cleaned = re.sub(r"https?://\S+", "", text or "")
    cleaned = re.sub(r"[`*_>#-]+", " ", cleaned)
    return _collapse_spaces(cleaned)


def _clip_reference_text(text: str, *, limit: int = MAX_REFERENCE_MESSAGE_CHARS) -> str:
    normalized = _normalize_prompt(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_messages(messages: list[dict]) -> list[dict]:
    serialized: list[dict] = []
    for message in messages or []:
        timestamp = message.get("timestamp")
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            timestamp_value = timestamp.astimezone(timezone.utc).isoformat()
        else:
            timestamp_value = str(timestamp or "")
        serialized.append(
            {
                "id": str(message.get("id") or ""),
                "role": str(message.get("role") or "assistant"),
                "content": str(message.get("content") or ""),
                "timestamp": timestamp_value,
            }
        )
    return serialized


def generate_title_from_prompts(prompts: list[str]) -> str:
    """Generate a concise title from the first 1-3 user prompts."""
    normalized = [_normalize_prompt(prompt) for prompt in prompts[:MAX_SEED_PROMPTS] if prompt and prompt.strip()]
    if not normalized:
        return DEFAULT_SESSION_TITLE

    first_clause = re.split(r"[.!?\n:]", normalized[0], maxsplit=1)[0]
    first_clause = _TITLE_PREFIX_PATTERN.sub("", first_clause).strip()
    corpus = " ".join(normalized)

    keywords: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9']+", corpus):
        lowered = token.lower()
        if len(lowered) <= 2 or lowered in _STOPWORDS:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        keywords.append(token)
        if len(keywords) >= MAX_TITLE_WORDS:
            break

    if keywords:
        title = " ".join(keywords)
    else:
        title = first_clause or normalized[0]

    title = _sanitize_title(title)
    return title[0].upper() + title[1:] if title else DEFAULT_SESSION_TITLE


async def create_session(agent_name: str, title: str | None = None) -> ChatSession:
    async with async_session() as db:
        session = ChatSession(agent_name=agent_name, title=_sanitize_title(title))
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await publish_event(
            "agents.sessions.updated",
            {"kind": "agent", "id": agent_name},
            {"agent_name": agent_name, "session_id": session.id, "action": "created"},
        )
        return session


async def list_sessions(agent_name: str) -> list[ChatSession]:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.agent_name == agent_name, ChatSession.deleted_at.is_(None))
            .order_by(
                func.coalesce(ChatSession.last_message_at, ChatSession.updated_at, ChatSession.created_at).desc(),
                ChatSession.id.desc(),
            )
        )
        return list(result.scalars().all())


async def get_session(agent_name: str, session_id: int, *, include_deleted: bool = False) -> ChatSession | None:
    async with async_session() as db:
        conditions = [ChatSession.id == session_id, ChatSession.agent_name == agent_name]
        if not include_deleted:
            conditions.append(ChatSession.deleted_at.is_(None))
        result = await db.execute(select(ChatSession).where(*conditions))
        return result.scalar_one_or_none()


async def ensure_session(agent_name: str, session_id: int | None = None) -> ChatSession:
    if session_id is None:
        return await create_session(agent_name=agent_name)

    session = await get_session(agent_name=agent_name, session_id=session_id)
    if not session:
        raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")
    return session


async def rename_session(agent_name: str, session_id: int, title: str) -> ChatSession:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.agent_name == agent_name,
                ChatSession.deleted_at.is_(None),
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")
        session.title = _sanitize_title(title)
        session.updated_at = _utcnow()
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await publish_event(
            "agents.sessions.updated",
            {"kind": "agent", "id": agent_name},
            {"agent_name": agent_name, "session_id": session.id, "action": "renamed"},
        )
        return session


async def clear_session_context(agent_name: str, session_id: int) -> ChatSession:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.agent_name == agent_name,
                ChatSession.deleted_at.is_(None),
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")

        await clear_memory(agent_name=agent_name, session_id=session_id)
        session.prompt_seed_count = 0
        session.last_message_at = None
        session.title = DEFAULT_SESSION_TITLE
        session.updated_at = _utcnow()
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await publish_event(
            "agents.sessions.updated",
            {"kind": "agent", "id": agent_name},
            {"agent_name": agent_name, "session_id": session.id, "action": "cleared"},
        )
        return session


async def get_session_messages(agent_name: str, session_id: int, limit: int = 200) -> list[dict]:
    async with async_session() as db:
        session_result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.agent_name == agent_name,
                ChatSession.deleted_at.is_(None),
            )
        )
        session = session_result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")
    return await list_session_messages(agent_name=agent_name, session_id=session_id, limit=limit)


async def build_session_reference_context(agent_name: str, session_id: int) -> str:
    session = await get_session(agent_name=agent_name, session_id=session_id)
    if not session:
        raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")

    messages = await list_session_messages(agent_name=agent_name, session_id=session_id, limit=200)
    prompts: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = _clip_reference_text(str(message.get("content") or ""))
        if content:
            prompts.append(content)
        if len(prompts) >= MAX_SEED_PROMPTS:
            break

    lines = [
        "[REFERENCED SESSION CONTEXT]",
        f"Agent: {agent_name}",
        f"Referenced session id: {session.id}",
        f"Referenced session title: {_sanitize_title(session.title)}",
        "This session is read-only reference context. Do not switch the active session unless the user explicitly asks.",
    ]

    if prompts:
        lines.append("First user prompts:")
        for prompt in prompts:
            lines.append(f"- {prompt}")

    if messages:
        lines.append("Recent messages:")
        for message in messages[-MAX_REFERENCE_MESSAGES:]:
            role = str(message.get("role") or "assistant").upper()
            content = _clip_reference_text(str(message.get("content") or ""))
            if content:
                lines.append(f"{role}: {content}")
    else:
        lines.append("This referenced session has no messages yet.")

    lines.append("[END REFERENCED SESSION CONTEXT]")
    return "\n".join(lines)


async def refresh_session_metadata(agent_name: str, session_id: int) -> ChatSession:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.agent_name == agent_name,
                ChatSession.deleted_at.is_(None),
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")

        prompts = []
        for message in await list_session_messages(
            agent_name=agent_name,
            session_id=session_id,
            limit=MAX_SEED_PROMPTS * 4,
        ):
            if message.get("role") == "user":
                prompts.append(str(message.get("content") or ""))
            if len(prompts) >= MAX_SEED_PROMPTS:
                break

        if prompts:
            session.prompt_seed_count = min(len(prompts), MAX_SEED_PROMPTS)
            if session.prompt_seed_count <= MAX_SEED_PROMPTS:
                session.title = generate_title_from_prompts(prompts)

        session.last_message_at = _utcnow()
        session.updated_at = _utcnow()
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await publish_event(
            "agents.sessions.updated",
            {"kind": "agent", "id": agent_name},
            {"agent_name": agent_name, "session_id": session.id, "action": "updated"},
        )
        return session


async def list_session_archives(agent_name: str, limit: int = 100) -> list[ChatSessionArchive]:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSessionArchive)
            .where(
                ChatSessionArchive.agent_name == agent_name,
                ChatSessionArchive.status == "archived",
                ChatSessionArchive.restored_at.is_(None),
                ChatSessionArchive.expires_at > _utcnow(),
            )
            .order_by(ChatSessionArchive.created_at.desc(), ChatSessionArchive.id.desc())
            .limit(max(1, min(limit, 500)))
        )
        return list(result.scalars().all())


async def archive_session(
    agent_name: str,
    session_id: int,
    *,
    source: str = "api",
    reason: str = "manual_delete",
) -> ChatSessionArchive:
    session = await get_session(agent_name=agent_name, session_id=session_id)
    if not session:
        raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")

    snapshot = _serialize_messages(await list_session_messages(agent_name=agent_name, session_id=session_id, limit=0))
    expires_at = _utcnow() + timedelta(days=SESSION_ARCHIVE_RETENTION_DAYS)

    async with async_session() as db:
        archive = ChatSessionArchive(
            session_id=session.id,
            agent_name=agent_name,
            title=_sanitize_title(session.title),
            source=source,
            reason=reason,
            status="pending",
            message_count=len(snapshot),
            snapshot_json=snapshot,
            expires_at=expires_at,
        )
        db.add(archive)
        await db.commit()
        await db.refresh(archive)

    try:
        await clear_memory(agent_name=agent_name, session_id=session_id)
    except Exception:
        async with async_session() as db:
            failed_archive = await db.get(ChatSessionArchive, archive.id)
            if failed_archive:
                failed_archive.status = "failed"
                await db.commit()
        raise

    async with async_session() as db:
        session_row = await db.get(ChatSession, session.id)
        archive_row = await db.get(ChatSessionArchive, archive.id)
        if not session_row or session_row.agent_name != agent_name:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")
        session_row.deleted_at = _utcnow()
        session_row.updated_at = _utcnow()
        archive_row.status = "archived"
        await db.commit()
        await db.refresh(archive_row)

    await publish_event(
        "agents.sessions.updated",
        {"kind": "agent", "id": agent_name},
        {
            "agent_name": agent_name,
            "session_id": session_id,
            "archive_id": archive.id,
            "action": "archived",
        },
    )
    return archive_row


async def archive_all_sessions(agent_name: str, *, source: str = "api") -> list[ChatSessionArchive]:
    archives: list[ChatSessionArchive] = []
    for session in await list_sessions(agent_name):
        archives.append(
            await archive_session(
                agent_name=agent_name,
                session_id=session.id,
                source=source,
                reason="bulk_delete",
            )
        )
    return archives


async def restore_session_archive(
    agent_name: str,
    archive_id: int,
    *,
    source: str = "api",
) -> ChatSession:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSessionArchive).where(
                ChatSessionArchive.id == archive_id,
                ChatSessionArchive.agent_name == agent_name,
            )
        )
        archive = result.scalar_one_or_none()
        if not archive or archive.status != "archived" or archive.restored_at is not None:
            raise ValueError(f"Chat session archive '{archive_id}' not found for agent '{agent_name}'")
        if archive.expires_at <= _utcnow():
            raise ValueError(f"Chat session archive '{archive_id}' has expired for agent '{agent_name}'")
        session = await db.get(ChatSession, archive.session_id)
        if not session or session.agent_name != agent_name:
            raise ValueError(f"Chat session '{archive.session_id}' not found for agent '{agent_name}'")
        if session.deleted_at is None:
            raise ValueError(f"Chat session '{archive.session_id}' is already active for agent '{agent_name}'")
        snapshot = list(archive.snapshot_json or [])

    await restore_session_messages(agent_name=agent_name, session_id=archive.session_id, messages=snapshot)

    async with async_session() as db:
        session = await db.get(ChatSession, archive.session_id)
        archive_row = await db.get(ChatSessionArchive, archive_id)
        if not session or session.agent_name != agent_name:
            raise ValueError(f"Chat session '{archive_row.session_id}' not found for agent '{agent_name}'")
        session.deleted_at = None
        session.updated_at = _utcnow()
        session.title = _sanitize_title(session.title or archive_row.title)
        archive_row.status = "restored"
        archive_row.restored_at = _utcnow()
        await db.commit()
        await db.refresh(session)

    await publish_event(
        "agents.sessions.updated",
        {"kind": "agent", "id": agent_name},
        {
            "agent_name": agent_name,
            "session_id": session.id,
            "archive_id": archive_id,
            "action": "restored",
            "source": source,
        },
    )
    return session


async def prune_expired_session_archives() -> dict[str, int]:
    now = _utcnow()
    cutoff = now - timedelta(days=SESSION_ARCHIVE_RETENTION_DAYS)

    async with async_session() as db:
        archived_result = await db.execute(
            delete(ChatSessionArchive).where(ChatSessionArchive.expires_at <= now)
        )
        deleted_sessions_result = await db.execute(
            delete(ChatSession).where(
                ChatSession.deleted_at.is_not(None),
                ChatSession.deleted_at <= cutoff,
            )
        )
        await db.commit()

    return {
        "chat_session_archives_deleted": archived_result.rowcount or 0,
        "chat_sessions_deleted": deleted_sessions_result.rowcount or 0,
    }
