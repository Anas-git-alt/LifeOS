from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bot.cogs.agents import AgentsCog


@pytest.mark.asyncio
async def test_send_agent_chat_includes_trace_and_discord_source(monkeypatch):
    cog = AgentsCog(bot=SimpleNamespace())
    api_post = AsyncMock(return_value={"response": "ok"})
    monkeypatch.setattr("bot.cogs.agents.api_post", api_post)

    result = await cog._send_agent_chat(
        agent_name="sandbox",
        message="remember blue cactus marker",
        source_message_id="123",
        source_channel_id="456",
    )

    payload = api_post.await_args.args[1]
    assert payload["trace_id"]
    assert payload["source_message_id"] == "123"
    assert payload["source_channel_id"] == "456"
    assert result["trace_id"] == payload["trace_id"]


def test_trim_error_shows_friendly_trace_id():
    request = httpx.Request("POST", "http://127.0.0.1:8100/api/agents/chat")
    response = httpx.Response(
        500,
        json={"detail": {"message": "Agent turn failed before a safe Discord response could be rendered.", "trace_id": "abc123"}},
        request=request,
    )
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    text = AgentsCog._trim_error(exc)

    assert "Backend 500" in text
    assert "trace_id=abc123" in text
    assert "safe Discord response" in text


@pytest.mark.asyncio
async def test_send_agent_result_recovers_when_discord_render_fails(monkeypatch):
    cog = AgentsCog(bot=SimpleNamespace())
    destination = SimpleNamespace(send=AsyncMock())

    async def _fail_render(*_args, **_kwargs):
        raise RuntimeError("embed failed")

    monkeypatch.setattr(cog, "_send_agent_result", _fail_render)

    await cog._send_agent_result_or_recover(
        destination=destination,
        agent_name="sandbox",
        result={"response": "Generated answer stored in history.", "trace_id": "trace99"},
    )

    sent_text = destination.send.await_args.args[0]
    assert "Generated answer stored in history." in sent_text
    assert "trace_id=trace99" in sent_text
