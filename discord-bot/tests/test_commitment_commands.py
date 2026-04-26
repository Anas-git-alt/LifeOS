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


class _SentMessage:
    def __init__(self, value: int):
        self.id = value
        self.reactions: list[str] = []

    async def add_reaction(self, emoji: str):
        self.reactions.append(emoji)


class _Ctx:
    def __init__(self):
        self.guild = _Dummy(1)
        self.channel = _Dummy(2, "planning")
        self.author = _Dummy(3)
        self.sent_messages: list[str] = []
        self.sent_embeds = []
        self.sent_objects: list[_SentMessage] = []

    async def send(self, message: str | None = None, *, embed=None):
        if message is not None:
            self.sent_messages.append(message)
        if embed is not None:
            self.sent_embeds.append(embed)
        sent = _SentMessage(1000 + len(self.sent_objects))
        self.sent_objects.append(sent)
        return sent

    def typing(self):
        return _Typing()


class _Channel:
    def __init__(self, value: int = 2):
        self.id = value
        self.sent_messages: list[str] = []
        self.sent_embeds = []
        self.sent_objects: list[_SentMessage] = []

    async def send(self, message: str | None = None, *, embed=None):
        if message is not None:
            self.sent_messages.append(message)
        if embed is not None:
            self.sent_embeds.append(embed)
        sent = _SentMessage(2000 + len(self.sent_objects))
        self.sent_objects.append(sent)
        return sent


class _Reference:
    def __init__(self, message_id: int | None):
        self.message_id = message_id


class _Message:
    def __init__(self, *, content: str, message_id: int = 50, reference_id: int | None = None, bot: bool = False, author_id: int = 3):
        self.id = message_id
        self.content = content
        self.reference = _Reference(reference_id) if reference_id else None
        self.channel = _Dummy(2, "planning")
        self.author = _Dummy(author_id)
        self.author.bot = bot
        self.reactions: list[str] = []

    async def add_reaction(self, emoji: str):
        self.reactions.append(emoji)


class _ReactionPayload:
    def __init__(self, *, message_id: int, user_id: int = 3, channel_id: int = 2, emoji: str = "✅"):
        self.message_id = message_id
        self.user_id = user_id
        self.channel_id = channel_id
        self.guild_id = 1
        self.emoji = emoji


def _not_found(path: str):
    raise httpx.HTTPStatusError(
        "not found",
        request=httpx.Request("GET", f"http://test{path}"),
        response=httpx.Response(404, request=httpx.Request("GET", f"http://test{path}")),
    )


@pytest.mark.asyncio
async def test_meeting_command_posts_meeting_intake(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/capture"
        assert payload["message"] == "Decision: build shared wiki. Action: add meeting intake."
        assert payload["source"] == "discord_meeting"
        assert payload["route_hint"] == "memory"
        return {
            "route": "memory",
            "event": {"id": 12, "domain": "work"},
            "wiki_proposals": [{"id": 5}],
            "entries": [{"id": 9}],
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.meeting.callback(cog, ctx, summary="Decision: build shared wiki. Action: add meeting intake.")

    assert len(ctx.sent_embeds) == 1
    embed = ctx.sent_embeds[0]
    assert embed.title == "Memory Review"
    assert "event #12" in embed.description


@pytest.mark.asyncio
async def test_notification_reply_listener_posts_job_reply(monkeypatch):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"ok": True}

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    bot = type("Bot", (), {"user": _Dummy(999)})()
    message = _Message(content="Done, invoice sent.", message_id=101, reference_id=99, bot=True, author_id=3)
    cog = AgentsCog(bot=bot)
    await cog.capture_notification_reply(message)

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
    assert message.reactions == ["✅"]


@pytest.mark.asyncio
async def test_notification_reply_listener_ignores_non_replies_commands_and_self_messages(monkeypatch):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"ok": True}

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    bot = type("Bot", (), {"user": _Dummy(3)})()
    cog = AgentsCog(bot=bot)
    await cog.capture_notification_reply(_Message(content="Done", reference_id=None))
    await cog.capture_notification_reply(_Message(content="!done 1", reference_id=99))
    await cog.capture_notification_reply(_Message(content="Done", reference_id=99, bot=True, author_id=3))

    assert calls == []


@pytest.mark.asyncio
async def test_agent_daily_log_proposal_uses_reaction_approval(monkeypatch):
    calls = []
    channel = _Channel()

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        if path == "/agents/chat":
            return {
                "response": "I can log this in Today: hydration x1, meal x1.",
                "pending_action_id": 44,
                "pending_action_type": "daily_log_batch",
                "session_id": 7,
                "session_title": "Should today",
            }
        if path == "/approvals/decide":
            return {"id": 44, "status": "executed", "result": "Logged: water and meal"}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)
    bot = type("Bot", (), {"user": _Dummy(999), "get_channel": lambda self, channel_id: channel})()
    cog = AgentsCog(bot=bot)
    ctx = _Ctx()

    await cog.ask_agent.callback(cog, ctx, agent_name="sandbox", message="i drank water and ate shawarma")

    sent = ctx.sent_objects[0]
    assert sent.reactions == ["✅"]
    assert cog.pending_daily_log_actions[sent.id]["action_id"] == 44

    await cog.approve_daily_log_reaction(_ReactionPayload(message_id=sent.id))

    assert calls[-1] == (
        "/approvals/decide",
        {"action_id": 44, "approved": True, "reviewed_by": "3", "source": "discord_reaction"},
    )
    assert "Logged: water and meal" in channel.sent_messages[-1]
    assert sent.id not in cog.pending_daily_log_actions


@pytest.mark.asyncio
async def test_agent_daily_log_reaction_continues_original_question(monkeypatch):
    calls = []
    channel = _Channel()

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        if path == "/agents/chat" and len([call for call in calls if call[0] == "/agents/chat"]) == 1:
            return {
                "response": "I can log this in Today: sleep 6h, hydration x1.",
                "pending_action_id": 44,
                "pending_action_type": "daily_log_batch",
                "session_id": 7,
                "session_title": "Should today",
            }
        if path == "/approvals/decide":
            return {"id": 44, "status": "executed", "result": "Logged: sleep and water"}
        if path == "/agents/chat":
            assert payload["message"] == "what should i do today?"
            assert "A daily log approval was just executed" in payload["transient_system_note"]
            assert "Do not ask to confirm that log again" in payload["transient_system_note"]
            return {"response": "Do invoice first.", "session_id": 7, "session_title": "Should today"}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)
    bot = type("Bot", (), {"user": _Dummy(999), "get_channel": lambda self, channel_id: channel})()
    cog = AgentsCog(bot=bot)
    ctx = _Ctx()

    await cog.ask_agent.callback(
        cog,
        ctx,
        agent_name="sandbox",
        message="what should i do today? i slept at 1:30 and wokeup at 7:30, drnk a cup of water",
    )

    sent = ctx.sent_objects[0]
    assert cog.pending_daily_log_actions[sent.id]["followup_request"] == "what should i do today?"

    await cog.approve_daily_log_reaction(_ReactionPayload(message_id=sent.id))

    assert channel.sent_messages[0].startswith("Daily log executed")
    assert channel.sent_embeds[-1].description == "Do invoice first."


@pytest.mark.asyncio
async def test_daily_log_proposal_reply_replaces_with_correction(monkeypatch):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        if path == "/approvals/decide":
            return {"id": 44, "status": "rejected", "result": "replaced"}
        if path == "/agents/chat":
            assert payload["message"] == "actually only meal"
            return {
                "response": "I can log this in Today: meal x1.",
                "pending_action_id": 45,
                "pending_action_type": "daily_log_batch",
                "session_id": 7,
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)
    bot = type("Bot", (), {"user": _Dummy(999)})()
    cog = AgentsCog(bot=bot)
    cog.pending_daily_log_actions[99] = {
        "action_id": 44,
        "agent_name": "sandbox",
        "session_id": 7,
        "guild_id": 1,
        "channel_id": 2,
        "author_id": 3,
    }
    channel = _Channel()
    message = _Message(content="actually only meal", message_id=101, reference_id=99, author_id=3)
    message.channel = channel

    await cog.capture_notification_reply(message)

    assert calls[0][0] == "/approvals/decide"
    assert calls[0][1]["approved"] is False
    assert calls[1][0] == "/agents/chat"
    assert channel.sent_objects[0].reactions == ["✅"]
    assert cog.pending_daily_log_actions[channel.sent_objects[0].id]["action_id"] == 45
    assert 99 not in cog.pending_daily_log_actions


@pytest.mark.asyncio
async def test_capturefollow_uses_active_commitment_capture_session(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/capture"
        assert payload["session_id"] == 77
        assert payload["new_session"] is False
        assert payload["route_hint"] == "commitment"
        assert payload["message"] == "using workday, before 4pm"
        return {
            "route": "commitment",
            "response": "Captured.",
            "session_id": 77,
            "entry": {"id": 5, "title": "Submit tax return paper request", "status": "processed"},
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()
    cog._set_active_session_id(ctx, "commitment-capture", 77)

    await cog.capture_follow.callback(cog, ctx, message="using workday, before 4pm")

    assert len(ctx.sent_embeds) == 1
    assert ctx.sent_embeds[0].title == "Capture Follow-up"


@pytest.mark.asyncio
async def test_capturefollow_accepts_explicit_session_id(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/capture"
        assert payload["session_id"] == 14
        assert payload["new_session"] is False
        assert payload["route_hint"] == "commitment"
        assert payload["message"] == "set a reminder for it at 1pm"
        return {
            "route": "commitment",
            "response": "Tracked.",
            "session_id": 14,
            "entry": {"id": 6, "title": "Tax papers", "status": "processed"},
        }

    monkeypatch.setattr("bot.cogs.agents.api_post", _fake_api_post)

    cog = AgentsCog(bot=object())
    ctx = _Ctx()

    await cog.capture_follow.callback(cog, ctx, message="14 set a reminder for it at 1pm")

    assert len(ctx.sent_embeds) == 1
    assert "Session #14" in ctx.sent_embeds[0].footer.text


@pytest.mark.asyncio
async def test_commit_command_posts_commitment_capture(monkeypatch):
    async def _fake_api_post(path: str, payload: dict):
        assert path == "/life/capture"
        assert payload["message"] == "Send invoice"
        assert payload["raw_message"] == "Send invoice tomorrow at 9am"
        assert payload["route_hint"] == "commitment"
        assert payload["target_channel"] == "planning"
        assert payload["target_channel_id"] == "2"
        assert payload["due_at"]
        return {
            "route": "commitment",
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
            "life_items": [{"id": 31, "title": "Send invoice"}],
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
