"""Tests for SQLite-backed memory summarisation and context assembly."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_entry(id_, agent_name, role, content, session_id=1):
    entry = MagicMock()
    entry.id = id_
    entry.agent_name = agent_name
    entry.role = role
    entry.content = content
    entry.session_id = session_id
    entry.timestamp = datetime.now(timezone.utc)
    return entry


def _force_sqlite(monkeypatch):
    monkeypatch.setattr("app.services.memory.settings.openviking_enabled", False)
    monkeypatch.setattr("app.services.memory.settings.memory_backend", "sqlite")


@pytest.mark.asyncio
async def test_summarise_session_below_threshold_returns_false(monkeypatch):
    _force_sqlite(monkeypatch)
    llm_call = AsyncMock()

    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=5)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=count_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.memory.async_session", return_value=mock_db):
        from app.services.memory import summarise_session

        result = await summarise_session(
            agent_name="test-agent",
            session_id=1,
            llm_call=llm_call,
            threshold=30,
        )

    assert result is False
    llm_call.assert_not_called()


@pytest.mark.asyncio
async def test_summarise_session_above_threshold_returns_true_and_compresses(monkeypatch):
    _force_sqlite(monkeypatch)
    summary_text = "- Point 1\n- Point 2"
    entries = [_make_entry(i, "test-agent", "user" if i % 2 == 0 else "assistant", f"msg {i}") for i in range(10)]

    call_count = 0

    async def _fake_session_ctx():
        mock_db = AsyncMock()

        async def _execute(_query):
            nonlocal call_count
            call_count += 1
            res = MagicMock()
            if call_count == 1:
                res.scalar = MagicMock(return_value=35)
            elif call_count == 2:
                res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=entries)))
            else:
                res.rowcount = 10
            return res

        mock_db.execute = _execute
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        return mock_db

    llm_call = AsyncMock(return_value=summary_text)
    sessions = [await _fake_session_ctx(), await _fake_session_ctx()]
    session_iter = iter(sessions)

    with patch("app.services.memory.async_session", side_effect=lambda: next(session_iter)):
        from app.services.memory import summarise_session

        result = await summarise_session(
            agent_name="test-agent",
            session_id=1,
            llm_call=llm_call,
            threshold=30,
        )

    assert result is True
    llm_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_context_prepends_summary_as_system_message(monkeypatch):
    _force_sqlite(monkeypatch)
    summary_entry = _make_entry(0, "test-agent", "summary", "[SUMMARY]\n- Decided X")
    user_entry = _make_entry(1, "test-agent", "user", "Hello")
    asst_entry = _make_entry(2, "test-agent", "assistant", "Hi")

    call_n = 0

    async def _execute(_query):
        nonlocal call_n
        call_n += 1
        res = MagicMock()
        if call_n == 1:
            res.scalar_one_or_none = MagicMock(return_value=summary_entry)
        else:
            res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[asst_entry, user_entry])))
        return res

    mock_db = AsyncMock()
    mock_db.execute = _execute
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.memory.async_session", return_value=mock_db):
        from app.services.memory import get_context

        messages = await get_context("test-agent", session_id=1)

    assert messages[0]["role"] == "system"
    assert "[SUMMARY]" in messages[0]["content"]
    roles = [m["role"] for m in messages[1:]]
    assert "user" in roles or "assistant" in roles


@pytest.mark.asyncio
async def test_get_context_no_summary_returns_plain_messages(monkeypatch):
    _force_sqlite(monkeypatch)
    user_entry = _make_entry(1, "test-agent", "user", "Hello")

    call_n = 0

    async def _execute(_query):
        nonlocal call_n
        call_n += 1
        res = MagicMock()
        if call_n == 1:
            res.scalar_one_or_none = MagicMock(return_value=None)
        else:
            res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[user_entry])))
        return res

    mock_db = AsyncMock()
    mock_db.execute = _execute
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.memory.async_session", return_value=mock_db):
        from app.services.memory import get_context

        messages = await get_context("test-agent", session_id=1)

    assert all(m["role"] != "system" for m in messages)
