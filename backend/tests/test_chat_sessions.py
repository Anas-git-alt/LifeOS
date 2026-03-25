"""Tests for chat session title generation."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.chat_sessions import (
    DEFAULT_SESSION_TITLE,
    build_session_reference_context,
    create_session,
    generate_title_from_prompts,
    refresh_session_metadata,
)
from app.services.openviking_client import (
    OpenVikingApiError,
    build_session_archive_messages_uri,
    build_session_messages_uri,
    openviking_client,
)


def _message_line(message_id: str, role: str, text: str, created_at: str) -> str:
    return json.dumps(
        {
            "id": message_id,
            "role": role,
            "created_at": created_at,
            "parts": [{"type": "text", "text": text}],
        }
    )


def test_generate_title_uses_prompt_context():
    title = generate_title_from_prompts(
        [
            "Help me design a rollback plan for the production deploy tonight.",
            "Also include smoke tests and alert checks.",
            "Keep it concise with clear ownership.",
            "This fourth prompt should be ignored for title seeding.",
        ]
    )
    lowered = title.lower()
    assert "rollback" in lowered
    assert "production" in lowered
    assert "smoke" in lowered


def test_generate_title_defaults_for_empty_input():
    assert generate_title_from_prompts([]) == DEFAULT_SESSION_TITLE
    assert generate_title_from_prompts(["   "]) == DEFAULT_SESSION_TITLE


@pytest.mark.asyncio
async def test_refresh_session_metadata_uses_archived_user_prompts(monkeypatch):
    monkeypatch.setattr("app.services.memory.settings.openviking_enabled", True)
    monkeypatch.setattr("app.services.memory.settings.memory_backend", "openviking")

    agent_name = f"sandbox-session-{uuid4().hex[:8]}"
    session = await create_session(agent_name=agent_name, title=None)

    archived_one = "\n".join(
        [
            _message_line("1", "user", "Help me debug the sandbox approval queue.", "2026-03-24T10:27:49.911Z"),
            _message_line("2", "assistant", "Let's inspect the approval policy.", "2026-03-24T10:27:49.958Z"),
        ]
    )
    archived_two = "\n".join(
        [
            _message_line("3", "user", "Also make session memory work again.", "2026-03-24T10:30:34.723Z"),
            _message_line("4", "assistant", "I'll trace the archived transcript path.", "2026-03-24T10:30:34.731Z"),
        ]
    )
    active = "\n".join(
        [
            _message_line("5", "user", "Keep current session continuity only.", "2026-03-24T10:34:57.975Z"),
            _message_line("6", "assistant", "Understood.", "2026-03-24T10:34:57.982Z"),
        ]
    )

    async def fake_read_content(uri: str, *, agent_name=None, offset=0, limit=-1):
        mapping = {
            build_session_archive_messages_uri(agent_name or session.agent_name, session.id, 1): archived_one,
            build_session_archive_messages_uri(agent_name or session.agent_name, session.id, 2): archived_two,
            build_session_messages_uri(agent_name or session.agent_name, session.id): active,
        }
        if uri in mapping:
            return mapping[uri]
        raise OpenVikingApiError("missing", code="NOT_FOUND", status_code=404)

    monkeypatch.setattr(openviking_client, "read_content", fake_read_content)

    refreshed = await refresh_session_metadata(agent_name=session.agent_name, session_id=session.id)

    assert refreshed.prompt_seed_count == 3
    lowered = refreshed.title.lower()
    assert "sandbox" in lowered
    assert "approval" in lowered
    assert "session" in lowered or "memory" in lowered


@pytest.mark.asyncio
async def test_build_session_reference_context_includes_title_prompts_and_recent_messages(monkeypatch):
    agent_name = f"sandbox-reference-{uuid4().hex[:8]}"
    session = await create_session(agent_name=agent_name, title="Summarize this repo")
    messages = [
        {"role": "user", "content": "Say hello", "timestamp": None},
        {"role": "assistant", "content": "Hello there", "timestamp": None},
        {"role": "user", "content": "Summarize this repo", "timestamp": None},
        {"role": "assistant", "content": "This repo has a backend and Discord bot.", "timestamp": None},
        {"role": "user", "content": "Keep it concise", "timestamp": None},
        {"role": "assistant", "content": "Understood.", "timestamp": None},
    ]
    monkeypatch.setattr(
        "app.services.chat_sessions.list_session_messages",
        AsyncMock(return_value=messages),
    )

    context = await build_session_reference_context(agent_name=agent_name, session_id=session.id)

    assert f"Referenced session id: {session.id}" in context
    assert "Referenced session title: Summarize this repo" in context
    assert "First user prompts:" in context
    assert "- Say hello" in context
    assert "- Summarize this repo" in context
    assert "Recent messages:" in context
    assert "ASSISTANT: This repo has a backend and Discord bot." in context
