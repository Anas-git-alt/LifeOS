from __future__ import annotations

import pytest

from bot.cogs.agents import AgentsCog


class _Dummy:
    def __init__(self, value: int, name: str | None = None):
        self.id = value
        self.name = name


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Ctx:
    def __init__(self):
        self.guild = _Dummy(1)
        self.channel = _Dummy(2, "planning")
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


@pytest.mark.asyncio
async def test_commit_command_posts_commitment_capture(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/commitments/capture"
        assert payload["message"] == "Send invoice"
        assert payload["target_channel"] == "planning"
        assert payload["target_channel_id"] == "2"
        assert payload["due_at"]
        return {
            "response": "Ready to promote",
            "session_id": 77,
            "needs_follow_up": False,
            "entry": {
                "id": 9,
                "title": "Send invoice",
                "status": "processed",
                "domain": "work",
                "kind": "commitment",
                "follow_up_questions": [],
            },
            "life_item": {"id": 31, "title": "Send invoice"},
            "follow_up_job": {"id": 44, "run_at": "2026-03-26T08:00:00Z"},
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.commit.callback(cog, ctx, message="Send invoice tomorrow at 9am")

    assert not ctx.sent_messages
    assert len(ctx.sent_embeds) == 1
    embed = ctx.sent_embeds[0]
    assert embed.title == "Commitment Capture"
    fields = {field.name: field.value for field in embed.fields}
    assert "Life item #31" in fields["Tracked Commitment"]
    assert fields["Session"].startswith("#77")


@pytest.mark.asyncio
async def test_snooze_command_parses_one_time_schedule(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/items/12/snooze"
        assert payload["due_at"]
        return {"id": 12, "title": "Send invoice", "due_at": "2026-03-26T08:00:00Z"}

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.snooze.callback(cog, ctx, "12", when="tomorrow at 9am")

    assert ctx.sent_messages
    assert "Snoozed #12" in ctx.sent_messages[0]


@pytest.mark.asyncio
async def test_commitfollow_accepts_explicit_session_id(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/commitments/capture"
        assert payload["session_id"] == 9
        return {
            "response": "Need one more detail",
            "session_id": 9,
            "needs_follow_up": True,
            "entry": {
                "id": 9,
                "title": "Fix bedtime routine",
                "status": "clarifying",
                "domain": "health",
                "kind": "habit",
                "follow_up_questions": ["What bedtime is realistic most nights?"],
            },
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.commit_follow.callback(cog, ctx, message="#9 realistic bedtime is 11:30pm")

    assert len(ctx.sent_embeds) == 1
    fields = {field.name: field.value for field in ctx.sent_embeds[0].fields}
    assert "Need Follow-up" in fields
    assert "`!commitfollow #9 <answer>`" in fields["Continue"]


@pytest.mark.asyncio
async def test_focuscoach_and_commitreview_commands(monkeypatch):
    async def _fake_api_get(path: str):
        if path == "/life/today":
            return {"top_focus": [{"id": 5, "title": "Send invoice"}]}
        if path == "/life/coach/daily-focus":
            return {
                "primary_item_id": 5,
                "why_now": "Overdue high-priority commitment.",
                "first_step": "Open invoice draft.",
                "defer_ids": [],
                "nudge_copy": "Move Send invoice one step now.",
                "fallback_used": False,
            }
        if path == "/life/coach/weekly-review":
            return {
                "wins": ["Closed 2 commitments."],
                "stale_commitments": ["none"],
                "repeat_blockers": ["none"],
                "promises_at_risk": ["none"],
                "simplify_next_week": ["Keep only 3 active commitments."],
                "fallback_used": False,
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("bot.cogs.agents.api_get", _fake_api_get)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.focus_coach.callback(cog, ctx)
    await cog.commitment_review.callback(cog, ctx)

    assert len(ctx.sent_messages) == 2
    assert "Primary: Send invoice" in ctx.sent_messages[0]
    assert "Wins: Closed 2 commitments." in ctx.sent_messages[1]
