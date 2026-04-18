from __future__ import annotations

import pytest

from bot.cogs.agents import AgentsCog
from bot.cogs.health import HealthCog


class _Dummy:
    def __init__(self, value: int):
        self.id = value


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Ctx:
    def __init__(self):
        self.guild = _Dummy(1)
        self.channel = _Dummy(2)
        self.author = _Dummy(3)
        self.sent_messages: list[str] = []
        self.sent_embeds = []

    async def send(self, message: str | None = None, *, embed=None):
        if message is not None:
            self.sent_messages.append(message)
        if embed is not None:
            self.sent_embeds.append(embed)

    def typing(self):
        return _Typing()


class _Bot:
    latency = 0.123


@pytest.mark.asyncio
async def test_status_command_smoke(monkeypatch):
    async def _fake_api_get(path: str):
        if path == "/health":
            return {"status": "ok", "version": "1.5.0"}
        if path == "/readiness":
            return {"status": "ready"}
        if path == "/approvals/stats":
            return {"pending": 2, "approved": 9, "rejected": 1}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("bot.cogs.health.api_get", _fake_api_get)

    cog = HealthCog(bot=_Bot())
    ctx = _Ctx()

    await cog.system_status.callback(cog, ctx)

    assert not ctx.sent_messages
    assert len(ctx.sent_embeds) == 1
    embed = ctx.sent_embeds[0]
    assert embed.title == "LifeOS Status"
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Backend"] == "ok v1.5.0"
    assert fields["Readiness"] == "ready"
    assert "online" in fields["Bot"]
    assert "pending=2" in fields["Approvals"]


@pytest.mark.asyncio
async def test_agents_command_smoke(monkeypatch):
    async def _fake_api_get(path: str):
        assert path == "/agents/"
        return [
            {
                "name": "sandbox",
                "enabled": True,
                "description": "General-purpose sandbox",
                "provider": "openrouter",
                "model": "openrouter/auto",
            },
            {
                "name": "daily-planner",
                "enabled": False,
                "description": "Daily planning specialist",
                "provider": "openai",
                "model": "gpt-5",
            },
        ]

    monkeypatch.setattr("bot.cogs.agents.api_get", _fake_api_get)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.list_agents.callback(cog, ctx)

    assert not ctx.sent_messages
    assert len(ctx.sent_embeds) == 1
    embed = ctx.sent_embeds[0]
    assert embed.title == "LifeOS Agents"
    field_names = [field.name for field in embed.fields]
    assert "sandbox (ON)" in field_names
    assert "daily-planner (OFF)" in field_names


@pytest.mark.asyncio
async def test_today_command_smoke(monkeypatch):
    async def _fake_api_get(path: str):
        assert path == "/life/today"
        return {
            "timezone": "Africa/Casablanca",
            "now": "2026-04-18T15:30:00+00:00",
            "top_focus": [{"id": 10, "title": "Deep work", "priority": "high"}],
            "due_today": [{"id": 11, "title": "Call family"}],
            "overdue": [{"id": 12, "title": "Send invoice"}],
        }

    monkeypatch.setattr("bot.cogs.agents.api_get", _fake_api_get)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.today.callback(cog, ctx)

    assert not ctx.sent_messages
    assert len(ctx.sent_embeds) == 1
    embed = ctx.sent_embeds[0]
    assert embed.title == "Today (Africa/Casablanca)"
    fields = {field.name: field.value for field in embed.fields}
    assert "#10 Deep work (high)" in fields["Top Focus"]
    assert "#11 Call family" in fields["Due Today"]
    assert "#12 Send invoice" in fields["Overdue"]


@pytest.mark.asyncio
async def test_ask_agent_warning_note_smoke(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/agents/chat"
        assert payload["agent_name"] == "sandbox"
        return {
            "response": "DISCORD_OK",
            "session_id": 7,
            "session_title": "Main session",
            "warnings": ["OpenViking memory was unavailable for this turn."],
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.ask_agent.callback(cog, ctx, agent_name="sandbox", message="Reply with exactly: DISCORD_OK")

    assert len(ctx.sent_embeds) == 1
    assert ctx.sent_embeds[0].title == "sandbox"
    assert ctx.sent_embeds[0].description == "DISCORD_OK"
    assert ctx.sent_messages == ["Note: OpenViking memory was unavailable for this turn."]
    assert cog._get_active_session_id(ctx, "sandbox") == 7
