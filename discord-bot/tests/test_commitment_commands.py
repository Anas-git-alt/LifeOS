from __future__ import annotations

import pytest
import httpx

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


class _Reference:
    def __init__(self, message_id: int | None):
        self.message_id = message_id


class _Message:
    def __init__(self, *, content: str, message_id: int = 50, reference_id: int | None = None, bot: bool = False):
        self.id = message_id
        self.content = content
        self.reference = _Reference(reference_id) if reference_id else None
        self.channel = _Dummy(2, "planning")
        self.author = _Dummy(3)
        self.author.bot = bot


def _not_found(path: str):
    raise httpx.HTTPStatusError(
        "not found",
        request=httpx.Request("GET", f"http://test{path}"),
        response=httpx.Response(404, request=httpx.Request("GET", f"http://test{path}")),
    )


@pytest.mark.asyncio
async def test_meeting_command_posts_meeting_intake(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/memory/intake/meeting"
        assert payload["summary"] == "Decision: build shared wiki. Action: add meeting intake."
        assert payload["source"] == "discord_meeting"
        return {
            "event": {"id": 12, "domain": "work"},
            "proposals": [{"id": 5}],
            "intake_entry_ids": [9],
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.meeting.callback(cog, ctx, summary="Decision: build shared wiki. Action: add meeting intake.")

    assert len(ctx.sent_embeds) == 1
    embed = ctx.sent_embeds[0]
    assert embed.title == "Meeting Intake"
    assert "event #12" in embed.description


@pytest.mark.asyncio
async def test_notification_reply_listener_posts_job_reply(monkeypatch):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"ok": True}

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    await cog.capture_notification_reply(
        _Message(content="Done, invoice sent.", message_id=101, reference_id=99)
    )

    assert calls == [
        (
            "/memory/intake/job-reply",
            {
                "notification_message_id": "99",
                "reply_text": "Done, invoice sent.",
                "discord_channel_id": "2",
                "discord_reply_message_id": "101",
                "discord_user_id": "3",
                "source": "discord_reply",
            },
        )
    ]


@pytest.mark.asyncio
async def test_notification_reply_listener_ignores_non_replies_commands_and_bots(monkeypatch):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"ok": True}

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    await cog.capture_notification_reply(_Message(content="Done", reference_id=None))
    await cog.capture_notification_reply(_Message(content="!done 1", reference_id=99))
    await cog.capture_notification_reply(_Message(content="Done", reference_id=99, bot=True))

    assert calls == []


@pytest.mark.asyncio
async def test_commit_command_posts_commitment_capture(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/commitments/capture"
        assert payload["message"] == "Send invoice"
        assert payload["raw_message"] == "Send invoice tomorrow at 9am"
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
    async def _fake_api_get(path: str):
        _not_found(path)

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

    monkeypatch.setattr("bot.cogs.agents.api_get", _fake_api_get)
    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.commit_follow.callback(cog, ctx, message="#9 realistic bedtime is 11:30pm")

    assert len(ctx.sent_embeds) == 1
    embed = ctx.sent_embeds[0]
    assert "`!commitfollow #9 <answer>`" not in embed.description
    assert "`!commitfollow 9 <answer>`" in embed.description
    fields = {field.name: field.value for field in embed.fields}
    assert "Need Follow-up" in fields
    assert "`!commitfollow 9 <answer>`" in fields["Continue"]
    assert "`!commitfollow session #9 <answer>`" in fields["Continue"]


@pytest.mark.asyncio
async def test_commitfollow_allows_answer_with_loose_today(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/commitments/capture"
        assert payload["session_id"] == 14
        assert payload["message"] == "make the mockup today"
        assert payload["due_at"] is None
        return {
            "response": "Tracked.",
            "session_id": 14,
            "needs_follow_up": False,
            "entry": {
                "id": 14,
                "title": "Create one pager",
                "status": "processed",
                "domain": "work",
                "kind": "commitment",
                "follow_up_questions": [],
            },
            "life_item": {"id": 40, "title": "Create one pager"},
            "follow_up_job": {"id": 45, "run_at": "2026-03-26T08:00:00Z"},
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.commit_follow.callback(cog, ctx, message="session #14 make the mockup today")

    assert not ctx.sent_messages
    assert len(ctx.sent_embeds) == 1
    fields = {field.name: field.value for field in ctx.sent_embeds[0].fields}
    assert "Life item #40" in fields["Tracked Commitment"]


@pytest.mark.asyncio
async def test_commitfollow_resolves_inbox_id_to_commitment_session(monkeypatch):
    async def _fake_api_get(path: str):
        assert path == "/life/inbox/3"
        return {
            "id": 3,
            "source_agent": "commitment-capture",
            "source_session_id": 14,
        }

    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/commitments/capture"
        assert payload["session_id"] == 14
        assert payload["message"] == "make the mockup today"
        return {
            "response": "Tracked.",
            "session_id": 14,
            "needs_follow_up": False,
            "entry": {
                "id": 3,
                "title": "Create one pager",
                "status": "processed",
                "domain": "work",
                "kind": "commitment",
                "follow_up_questions": [],
            },
            "life_item": {"id": 40, "title": "Create one pager"},
            "follow_up_job": {"id": 45, "run_at": "2026-03-26T08:00:00Z"},
        }

    monkeypatch.setattr("bot.cogs.agents.api_get", _fake_api_get)
    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.commit_follow.callback(cog, ctx, message="3 make the mockup today")

    assert not ctx.sent_messages
    fields = {field.name: field.value for field in ctx.sent_embeds[0].fields}
    assert "Life item #40" in fields["Tracked Commitment"]


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
