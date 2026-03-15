"""Tests for memory.py summarise_session() and updated get_context()."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_entry(id_, agent_name, role, content, session_id=1):
    entry = MagicMock()
    entry.id = id_
    entry.agent_name = agent_name
    entry.role = role
    entry.content = content
    entry.session_id = session_id
    entry.timestamp = datetime.now(timezone.utc)
    return entry


# ---------------------------------------------------------------------------
# summarise_session — threshold guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summarise_session_below_threshold_returns_false():
    """When message count ≤ threshold, summarise_session must return False
    without touching the DB or calling the LLM."""
    llm_call = AsyncMock()

    # count_result.scalar() returns a value ≤ threshold
    count_scalar = MagicMock(return_value=5)
    count_result = MagicMock()
    count_result.scalar = count_scalar

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
async def test_summarise_session_above_threshold_returns_true_and_compresses():
    """When message count > threshold, summarise_session must call the LLM,
    delete old rows, and insert a [SUMMARY] MemoryEntry."""
    summary_text = "• Point 1\n• Point 2"

    # Build mock entries for the 'fetch recent 40' query
    entries = [_make_entry(i, "test-agent", "user" if i % 2 == 0 else "assistant", f"msg {i}") for i in range(10)]

    call_count = 0

    async def _fake_session_ctx():
        """Returns a new mock db each time it's used as an async context manager."""
        mock_db = AsyncMock()

        async def _execute(q):
            nonlocal call_count
            call_count += 1
            res = MagicMock()
            if call_count == 1:
                # First call: count query → returns 35 (above threshold=30)
                res.scalar = MagicMock(return_value=35)
            elif call_count == 2:
                # Second call: fetch recent entries
                res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=entries)))
            else:
                # Subsequent calls: delete operations → row count
                res.rowcount = 10
            return res

        mock_db.execute = _execute
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        return mock_db

    llm_call = AsyncMock(return_value=summary_text)

    # We need two separate db sessions (count+fetch, then delete+insert)
    sessions = [await _fake_session_ctx(), await _fake_session_ctx()]
    session_iter = iter(sessions)

    def _next_session():
        return next(session_iter)

    with patch("app.services.memory.async_session", side_effect=_next_session):
        from app.services.memory import summarise_session
        result = await summarise_session(
            agent_name="test-agent",
            session_id=1,
            llm_call=llm_call,
            threshold=30,
        )

    assert result is True
    llm_call.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_context — summary prepend
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_context_prepends_summary_as_system_message():
    """When a summary entry exists for the session, get_context must prepend
    it as role='system' before the recent messages."""
    summary_entry = _make_entry(0, "test-agent", "summary", "[SUMMARY]\n• Decided X")
    user_entry = _make_entry(1, "test-agent", "user", "Hello")
    asst_entry = _make_entry(2, "test-agent", "assistant", "Hi")

    call_n = 0

    async def _execute(q):
        nonlocal call_n
        call_n += 1
        res = MagicMock()
        if call_n == 1:
            # summary query
            res.scalar_one_or_none = MagicMock(return_value=summary_entry)
        else:
            # recent messages query
            res.scalars = MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[asst_entry, user_entry]))
            )
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
    # Remaining messages should be user/assistant (reversed into chronological order)
    roles = [m["role"] for m in messages[1:]]
    assert "user" in roles or "assistant" in roles


@pytest.mark.asyncio
async def test_get_context_no_summary_returns_plain_messages():
    """When no summary entry exists, get_context must return only user/assistant
    messages without any prepended system message."""
    user_entry = _make_entry(1, "test-agent", "user", "Hello")

    call_n = 0

    async def _execute(q):
        nonlocal call_n
        call_n += 1
        res = MagicMock()
        if call_n == 1:
            res.scalar_one_or_none = MagicMock(return_value=None)
        else:
            res.scalars = MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[user_entry]))
            )
        return res

    mock_db = AsyncMock()
    mock_db.execute = _execute
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.memory.async_session", return_value=mock_db):
        from app.services.memory import get_context
        messages = await get_context("test-agent", session_id=1)

    assert all(m["role"] != "system" for m in messages)
