from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.cogs.automation import AutomationCog


def _make_ctx():
    author = SimpleNamespace(id=22)
    author.__str__ = lambda self=author: "tester"
    return SimpleNamespace(
        guild=SimpleNamespace(id=11, text_channels=[]),
        channel=SimpleNamespace(id=33),
        author=author,
        send=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_cancel_clears_pending_state():
    cog = AutomationCog(bot=SimpleNamespace())
    ctx = _make_ctx()
    cog.pending[cog._state_key(ctx)] = {"type": "job", "data": {}, "missing": ["schedule"]}

    await cog.cancel_followup.callback(cog, ctx)

    assert cog._state_key(ctx) not in cog.pending
    ctx.send.assert_awaited_with("Cleared the pending automation flow.")


@pytest.mark.asyncio
async def test_reply_completes_schedule_followup(monkeypatch):
    cog = AutomationCog(bot=SimpleNamespace())
    ctx = _make_ctx()
    cog.pending[cog._state_key(ctx)] = {
        "type": "job",
        "data": {
            "name": "NL: review notes",
            "description": "Natural-language reminder job: review notes",
            "agent_name": "sandbox",
            "timezone": "Africa/Casablanca",
            "notification_mode": "silent",
            "prompt_template": "review notes",
        },
        "missing": ["schedule"],
    }
    monkeypatch.setattr(
        "bot.cogs.automation.parse_schedule_value",
        lambda _value, default_timezone="Africa/Casablanca": {
            "data": {"schedule_type": "once", "cron_expression": None, "run_at": "2026-03-25T09:00:00"},
            "errors": [],
        },
    )
    submit_job = AsyncMock()
    monkeypatch.setattr(cog, "_submit_job_proposal", submit_job)

    await cog.continue_followup.callback(cog, ctx, answer="tomorrow at 9am")

    submit_job.assert_awaited()
    assert cog._state_key(ctx) not in cog.pending


@pytest.mark.asyncio
async def test_submit_job_proposal_serializes_once_run_at_as_utc(monkeypatch):
    cog = AutomationCog(bot=SimpleNamespace())
    ctx = _make_ctx()
    api_post = AsyncMock(return_value={"pending_action_id": 30})
    monkeypatch.setattr("bot.cogs.automation.api_post", api_post)

    await cog._submit_job_proposal(
        ctx,
        {
            "name": "NL: buy medicine",
            "description": "Natural-language reminder job: buy medicine",
            "agent_name": "sandbox",
            "schedule_type": "once",
            "cron_expression": None,
            "run_at": datetime(2026, 3, 25, 7, 16, 57, 381182),
            "timezone": "Africa/Casablanca",
            "notification_mode": "channel",
            "target_channel": "test",
            "target_channel_id": "1486255985587781702",
            "prompt_template": "buy medicine",
        },
    )

    details = api_post.await_args.args[1]["details"]
    assert details["run_at"].endswith("+00:00")
    assert details["notification_mode"] == "channel"
    assert details["target_channel_id"] == "1486255985587781702"
