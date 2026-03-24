"""Chat session service with per-agent history and auto-generated titles."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from app.database import async_session
from app.models import ChatSession
from app.services.events import publish_event
from app.services.memory import clear_memory, list_session_messages

DEFAULT_SESSION_TITLE = "New chat"
MAX_TITLE_LENGTH = 160
MAX_TITLE_WORDS = 12
MAX_SEED_PROMPTS = 3

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
            .where(ChatSession.agent_name == agent_name)
            .order_by(
                func.coalesce(ChatSession.last_message_at, ChatSession.updated_at, ChatSession.created_at).desc(),
                ChatSession.id.desc(),
            )
        )
        return list(result.scalars().all())


async def get_session(agent_name: str, session_id: int) -> ChatSession | None:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.agent_name == agent_name)
        )
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
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.agent_name == agent_name)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")
        session.title = _sanitize_title(title)
        session.updated_at = datetime.now(timezone.utc)
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
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.agent_name == agent_name)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")

        await clear_memory(agent_name=agent_name, session_id=session_id)
        session.prompt_seed_count = 0
        session.last_message_at = None
        session.title = DEFAULT_SESSION_TITLE
        session.updated_at = datetime.now(timezone.utc)
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
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.agent_name == agent_name)
        )
        session = session_result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Chat session '{session_id}' not found for agent '{agent_name}'")
    return await list_session_messages(agent_name=agent_name, session_id=session_id, limit=limit)


async def refresh_session_metadata(agent_name: str, session_id: int) -> ChatSession:
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.agent_name == agent_name)
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

        session.last_message_at = datetime.now(timezone.utc)
        session.updated_at = datetime.now(timezone.utc)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await publish_event(
            "agents.sessions.updated",
            {"kind": "agent", "id": agent_name},
            {"agent_name": agent_name, "session_id": session.id, "action": "updated"},
        )
        return session
