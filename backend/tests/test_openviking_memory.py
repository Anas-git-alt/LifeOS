"""Tests for OpenViking-backed memory behavior."""

from unittest.mock import AsyncMock

import pytest

from app.services.memory import get_context, save_message, summarise_session
from app.services.openviking_client import OpenVikingUnavailableError


def _enable_openviking(monkeypatch):
    monkeypatch.setattr("app.services.memory.settings.openviking_enabled", True)
    monkeypatch.setattr("app.services.memory.settings.memory_backend", "openviking")


@pytest.mark.asyncio
async def test_get_context_prepends_openviking_summary(monkeypatch):
    _enable_openviking(monkeypatch)
    monkeypatch.setattr(
        "app.services.memory.openviking_client.read_session_summary",
        AsyncMock(return_value="[SUMMARY]\n- Key fact"),
    )
    monkeypatch.setattr(
        "app.services.memory.openviking_client.read_session_messages",
        AsyncMock(
            return_value=[
                {
                    "id": "1",
                    "role": "user",
                    "created_at": "2026-03-23T12:00:00Z",
                    "parts": [{"type": "text", "text": "Hello"}],
                },
                {
                    "id": "2",
                    "role": "assistant",
                    "created_at": "2026-03-23T12:01:00Z",
                    "parts": [{"type": "text", "text": "Hi there"}],
                },
            ]
        ),
    )

    messages = await get_context("sandbox", session_id=42)

    assert messages[0] == {"role": "system", "content": "[SUMMARY]\n- Key fact"}
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"


@pytest.mark.asyncio
async def test_summarise_session_writes_openviking_summary(monkeypatch):
    _enable_openviking(monkeypatch)
    monkeypatch.setattr(
        "app.services.memory.openviking_client.read_session_messages",
        AsyncMock(
            return_value=[
                {
                    "id": str(i),
                    "role": "user" if i % 2 == 0 else "assistant",
                    "created_at": "2026-03-23T12:00:00Z",
                    "parts": [{"type": "text", "text": f"msg {i}"}],
                }
                for i in range(8)
            ]
        ),
    )
    write_summary = AsyncMock()
    monkeypatch.setattr(
        "app.services.memory.openviking_client.write_session_summary",
        write_summary,
    )
    llm_call = AsyncMock(return_value="- Fresh summary")

    result = await summarise_session("sandbox", 7, llm_call=llm_call, threshold=3)

    assert result is True
    llm_call.assert_awaited_once()
    write_summary.assert_awaited_once_with("sandbox", 7, "[SUMMARY]\n- Fresh summary")


@pytest.mark.asyncio
async def test_save_message_openviking_failure_raises(monkeypatch):
    _enable_openviking(monkeypatch)
    monkeypatch.setattr(
        "app.services.memory.openviking_client.add_message",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    with pytest.raises(OpenVikingUnavailableError):
        await save_message("sandbox", "user", "hello", session_id=1)
