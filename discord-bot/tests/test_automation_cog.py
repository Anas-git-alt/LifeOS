"""Automation cog follow-up flow tests."""

import pytest

from bot.cogs.automation import AutomationCog


class _Dummy:
    def __init__(self, value: int):
        self.id = value


class _Ctx:
    def __init__(self):
        self.guild = _Dummy(1)
        self.channel = _Dummy(2)
        self.author = _Dummy(3)
        self.sent_messages: list[str] = []

    async def send(self, message: str):
        self.sent_messages.append(message)


@pytest.mark.asyncio
async def test_schedule_followup_flow(monkeypatch):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"pending_action_id": 42}

    monkeypatch.setattr("bot.cogs.automation.api_post", _fake_api_post)

    cog = AutomationCog(bot=object())
    ctx = _Ctx()

    await cog.create_job_from_nl.callback(cog, ctx, prompt="remind me to stretch")
    assert "Need more info" in ctx.sent_messages[-1]

    await cog.continue_followup.callback(cog, ctx, answer="#fitness-log")
    await cog.continue_followup.callback(cog, ctx, answer="daily-planner")
    await cog.continue_followup.callback(cog, ctx, answer="every weekday at 7:30")

    assert calls, "Expected API proposal submission after collecting follow-ups"
    assert calls[0][0] == "/jobs/propose"
