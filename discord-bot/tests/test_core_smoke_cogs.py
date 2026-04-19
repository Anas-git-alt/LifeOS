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
            "scorecard": {
                "sleep_hours": 8,
                "meals_count": 1,
                "hydration_count": 2,
                "training_status": "done",
                "protein_hit": True,
                "family_action_done": False,
                "top_priority_completed_count": 1,
                "shutdown_done": False,
                "rescue_status": "watch",
            },
            "next_prayer": {
                "name": "Dhuhr",
                "starts_at": "2026-04-18T12:30:00+01:00",
                "ends_at": "2026-04-18T15:45:00+01:00",
            },
            "rescue_plan": {
                "status": "watch",
                "headline": "Hydration is behind.",
                "actions": ["Log water twice in the next hour.", "Protect Dhuhr window."],
            },
            "sleep_protocol": {
                "bedtime_target": "23:00",
                "wake_target": "07:00",
                "caffeine_cutoff": "14:00",
                "wind_down_checklist": ["Dim lights", "Prep clothes"],
                "sleep_hours_logged": 8,
                "bedtime_logged": "23:05",
                "wake_time_logged": "07:10",
            },
            "streaks": [
                {"label": "Sleep 7h+", "current_streak": 3, "today_status": "hit", "hits_last_7": 4},
                {"label": "Hydration 2+", "current_streak": 2, "today_status": "pending", "hits_last_7": 5},
            ],
            "trend_summary": {
                "window_days": 7,
                "average_completion_pct": 71,
                "best_day": {"date": "2026-04-17", "completion_pct": 86},
                "recent_days": [
                    {"date": "2026-04-15", "completion_pct": 57},
                    {"date": "2026-04-16", "completion_pct": 71},
                    {"date": "2026-04-17", "completion_pct": 86},
                ],
            },
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
    assert "Sleep: 8h | Meals: 1 | Water: 2" in fields["Scorecard"]
    assert "Dhuhr" in fields["Next Prayer"]
    assert "Status: watch" in fields["Rescue Plan"]
    assert "Target: 23:00 -> 07:00" in fields["Sleep Protocol"]
    assert "Sleep 7h+: 3 streak | today hit | 7d 4/7" in fields["Streaks"]
    assert "Average: 71%" in fields["7-Day Trend"]
    assert "#10 Deep work (high)" in fields["Top Focus"]
    assert "#11 Call family" in fields["Due Today"]
    assert "#12 Send invoice" in fields["Overdue"]


@pytest.mark.asyncio
async def test_today_command_shows_empty_sections(monkeypatch):
    async def _fake_api_get(path: str):
        assert path == "/life/today"
        return {
            "timezone": "Africa/Casablanca",
            "now": "2026-04-19T10:04:28.544068+01:00",
            "scorecard": {
                "sleep_hours": None,
                "meals_count": 0,
                "hydration_count": 0,
                "training_status": None,
                "protein_hit": False,
                "family_action_done": False,
                "top_priority_completed_count": 0,
                "shutdown_done": False,
                "rescue_status": "watch",
            },
            "top_focus": [],
            "due_today": [],
            "overdue": [],
            "streaks": [],
            "trend_summary": None,
            "sleep_protocol": None,
            "rescue_plan": None,
            "next_prayer": None,
        }

    monkeypatch.setattr("bot.cogs.agents.api_get", _fake_api_get)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.today.callback(cog, ctx)

    assert not ctx.sent_messages
    assert len(ctx.sent_embeds) == 1
    fields = {field.name: field.value for field in ctx.sent_embeds[0].fields}
    assert fields["Top Focus"] == "none"
    assert fields["Due Today"] == "none"
    assert fields["Overdue"] == "none"
    assert fields["Streaks"] == "none"
    assert fields["7-Day Trend"] == "none"


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
