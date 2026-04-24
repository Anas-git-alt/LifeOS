"""Tests for OpenViking-backed memory behavior."""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.memory import get_context, save_message, summarise_session
from app.services.openviking_client import (
    OpenVikingApiError,
    OpenVikingUnavailableError,
    build_session_archive_root_uri,
    build_session_archive_messages_uri,
    build_session_messages_uri,
    openviking_client,
)


def _enable_openviking(monkeypatch):
    monkeypatch.setattr("app.services.memory.settings.openviking_enabled", True)
    monkeypatch.setattr("app.services.memory.settings.memory_backend", "openviking")


def _message_line(message_id: str, role: str, text: str, created_at: str) -> str:
    return json.dumps(
        {
            "id": message_id,
            "role": role,
            "created_at": created_at,
            "parts": [{"type": "text", "text": text}],
        }
    )


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
async def test_get_context_reads_archived_messages_when_active_session_is_empty(monkeypatch):
    _enable_openviking(monkeypatch)
    monkeypatch.setattr(
        "app.services.memory.openviking_client.read_session_summary",
        AsyncMock(return_value=""),
    )

    archived_one = "\n".join(
        [
            _message_line("1", "user", "First question", "2026-03-24T10:27:49.911Z"),
            _message_line("2", "assistant", "First answer", "2026-03-24T10:27:49.958Z"),
        ]
    )
    archived_two = "\n".join(
        [
            _message_line("3", "user", "Second question", "2026-03-24T10:30:34.723Z"),
            _message_line("4", "assistant", "Second answer", "2026-03-24T10:30:34.731Z"),
            _message_line("5", "user", "What did I just ask you to do?", "2026-03-24T10:34:57.975Z"),
        ]
    )

    async def fake_read_content(uri: str, *, agent_name=None, offset=0, limit=-1):
        mapping = {
            build_session_archive_messages_uri("sandbox", 59, 1): archived_one,
            build_session_archive_messages_uri("sandbox", 59, 2): archived_two,
            build_session_messages_uri("sandbox", 59): "",
        }
        if uri in mapping:
            return mapping[uri]
        raise OpenVikingApiError("missing", code="NOT_FOUND", status_code=404)

    monkeypatch.setattr("app.services.memory.openviking_client.read_content", fake_read_content)

    messages = await get_context("sandbox", session_id=59, limit=10)

    assert [item["content"] for item in messages] == [
        "First question",
        "First answer",
        "Second question",
        "Second answer",
        "What did I just ask you to do?",
    ]


@pytest.mark.asyncio
async def test_openviking_client_merges_archived_and_active_session_messages(monkeypatch):
    archived_one = "\n".join(
        [
            _message_line("1", "user", "Question one", "2026-03-24T10:27:49.911Z"),
            _message_line("2", "assistant", "Answer one", "2026-03-24T10:27:49.958Z"),
        ]
    )
    archived_two = _message_line("3", "user", "Question two", "2026-03-24T10:30:34.723Z")
    active = "\n".join(
        [
            _message_line("3", "user", "Question two", "2026-03-24T10:30:34.723Z"),
            _message_line("4", "assistant", "Answer two", "2026-03-24T10:30:34.731Z"),
        ]
    )

    async def fake_read_content(uri: str, *, agent_name=None, offset=0, limit=-1):
        mapping = {
            build_session_archive_messages_uri("sandbox", 42, 1): archived_one,
            build_session_archive_messages_uri("sandbox", 42, 2): archived_two,
            build_session_messages_uri("sandbox", 42): active,
        }
        if uri in mapping:
            return mapping[uri]
        raise OpenVikingApiError("missing", code="NOT_FOUND", status_code=404)

    monkeypatch.setattr(openviking_client, "read_content", fake_read_content)

    messages = await openviking_client.read_session_messages("sandbox", 42)

    assert [item["id"] for item in messages] == ["1", "2", "3", "4"]
    assert [item["parts"][0]["text"] for item in messages] == [
        "Question one",
        "Answer one",
        "Question two",
        "Answer two",
    ]


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


@pytest.mark.asyncio
async def test_save_message_openviking_retries_commit_in_progress(monkeypatch):
    _enable_openviking(monkeypatch)
    add_message = AsyncMock(return_value={})
    commit_session = AsyncMock(
        side_effect=[
            RuntimeError("Session lifeos:sandbox:62 already has a commit in progress"),
            RuntimeError("Session lifeos:sandbox:62 already has a commit in progress"),
        ]
    )
    monkeypatch.setattr("app.services.memory.openviking_client.add_message", add_message)
    monkeypatch.setattr("app.services.memory.openviking_client.commit_session", commit_session)

    await save_message("sandbox", "assistant", "hello", session_id=62)

    add_message.assert_awaited_once()
    assert commit_session.await_count == 2


@pytest.mark.asyncio
async def test_save_message_openviking_repairs_failed_archive_before_retry(monkeypatch):
    _enable_openviking(monkeypatch)
    add_message = AsyncMock(return_value={})
    commit_session = AsyncMock(
        side_effect=[
            RuntimeError("Session lifeos:sandbox:62 has unresolved failed archive archive_001; fix it before committing again."),
            {},
        ]
    )
    repair = AsyncMock(return_value=[{"archive_id": "archive_001"}])
    monkeypatch.setattr("app.services.memory.openviking_client.add_message", add_message)
    monkeypatch.setattr("app.services.memory.openviking_client.commit_session", commit_session)
    monkeypatch.setattr("app.services.memory.openviking_client.repair_failed_session_archives", repair)

    await save_message("sandbox", "assistant", "hello", session_id=62)

    add_message.assert_awaited_once()
    repair.assert_awaited_once_with("sandbox", 62)
    assert commit_session.await_count == 2


@pytest.mark.asyncio
async def test_openviking_client_repair_failed_session_archives(monkeypatch):
    archive_uri = build_session_archive_root_uri("sandbox", 62, 1)
    messages = "\n".join(
        [
            _message_line("1", "user", "Question", "2026-03-24T10:27:49.911Z"),
            _message_line("2", "assistant", "Answer", "2026-03-24T10:27:49.958Z"),
        ]
    )
    writes: list[tuple[str, str]] = []
    removed: list[str] = []

    async def fake_read_content(uri: str, *, agent_name=None, offset=0, limit=-1):
        mapping = {
            f"{archive_uri}/messages.jsonl": messages,
            f"{archive_uri}/.failed.json": '{"stage":"memory_extraction"}',
        }
        if uri in mapping:
            return mapping[uri]
        raise OpenVikingApiError("missing", code="NOT_FOUND", status_code=404)

    async def fake_write_content(uri: str, content: str, **_kwargs):
        writes.append((uri, content))
        return {}

    async def fake_rm(uri: str, *, recursive=True):
        removed.append(uri)
        return {}

    monkeypatch.setattr(openviking_client, "read_content", fake_read_content)
    monkeypatch.setattr(openviking_client, "write_content", fake_write_content)
    monkeypatch.setattr(openviking_client, "rm", fake_rm)

    repaired = await openviking_client.repair_failed_session_archives("sandbox", 62)

    assert repaired[0]["archive_id"] == "archive_001"
    assert writes[0][0] == f"{archive_uri}/.done"
    assert '"starting_message_id": "1"' in writes[0][1]
    assert '"ending_message_id": "2"' in writes[0][1]
    assert removed == [f"{archive_uri}/.failed.json"]
