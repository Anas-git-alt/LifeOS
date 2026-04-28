from __future__ import annotations

from datetime import datetime, timezone
import pytest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.database import async_session
from app.models import Agent, CaptureItemResponse, ChatSession, ContextEvent, IntakeCaptureResponse, IntakeEntry, UnifiedCaptureRequest
from app.routers.life import (
    _clean_commitment_title,
    _commitment_followup_note,
    _detail_questions_for_capture,
    _infer_commitment_domain,
    _infer_capture_due_at,
    _priority_overrides_for_capture,
    _select_capture_route,
    capture_life,
)
from app.services.capture_v2 import split_capture_message
from app.services.life import get_today_agenda


def _fake_schedule():
    return {"next_prayer": None, "windows": []}


async def _create_agent_session(agent_name: str) -> int:
    async with async_session() as db:
        agent = Agent(name=agent_name, system_prompt="Test agent", provider="test", model="test", enabled=True)
        session = ChatSession(agent_name=agent_name, title="Test session")
        db.add(agent)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session.id


def test_unified_capture_route_selector_sorts_common_inputs():
    assert _select_capture_route(UnifiedCaptureRequest(message="Send invoice tomorrow at 9am")) == "commitment"
    assert _select_capture_route(UnifiedCaptureRequest(message="Meeting notes: decided to keep one capture inbox")) == "memory"
    assert _select_capture_route(UnifiedCaptureRequest(message="I want to build better sleep habits")) == "intake"


@pytest.mark.asyncio
async def test_unified_capture_auto_route_uses_session_owner(monkeypatch):
    session_id = await _create_agent_session("intake-inbox")

    async def _fake_capture_inbox(data):
        assert data.session_id == session_id
        assert data.new_session is False
        return IntakeCaptureResponse(response="Continued intake.", session_id=session_id)

    monkeypatch.setattr("app.routers.life.capture_inbox", _fake_capture_inbox)

    result = await capture_life(
        UnifiedCaptureRequest(
            message="send invoice follow-up detail",
            session_id=session_id,
            new_session=False,
            route_hint="auto",
        )
    )

    assert result.route == "intake"
    assert result.response == "Continued intake."


@pytest.mark.asyncio
async def test_agentic_capture_followup_creates_life_items(monkeypatch):
    fixed_now = datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr("app.routers.life.datetime", FrozenDateTime)
    session_id = await _create_agent_session("intake-inbox")
    async with async_session() as db:
        entry = IntakeEntry(
            source="agent_capture",
            source_agent="intake-inbox",
            source_session_id=session_id,
            raw_text=(
                "i have a wedding that i am invited to next sunday 3rd may, "
                "i need to take my suit to the ironing shop on Thursday to pick it up on Saturday morning"
            ),
            title="Wedding suit plan",
            domain="planning",
            kind="idea",
            status="clarifying",
            follow_up_questions_json=["What concrete tasks should be tracked?"],
        )
        db.add(entry)
        await db.commit()

    monkeypatch.setattr(
        "app.routers.life.chat_completion",
        AsyncMock(
            return_value=(
                '{"intent":"create_life_items","response":"Split into 3 tasks.",'
                '"actions":['
                '{"title":"Take suit to ironing shop","domain":"health","kind":"task","priority":"medium","due_at":"2026-04-30T10:00:00+01:00","notes":"Wedding suit prep."},'
                '{"title":"Pick up suit from ironing shop","domain":"planning","kind":"task","priority":"medium","due_at":"2026-05-02T10:00:00+01:00","notes":"Saturday morning pickup."},'
                '{"title":"Attend wedding","domain":"planning","kind":"task","priority":"medium","due_at":"2026-05-03T12:00:00+01:00","notes":"Exact wedding time was not captured."}'
                "]}"
            )
        ),
    )

    result = await capture_life(
        UnifiedCaptureRequest(
            message="split it into 3 tasks",
            session_id=session_id,
            new_session=False,
            route_hint="auto",
            timezone="Africa/Casablanca",
        )
    )

    assert result.route == "intake"
    assert [item.title for item in result.life_items] == [
        "Take suit to ironing shop",
        "Pick up suit from ironing shop",
        "Attend wedding",
    ]
    assert result.life_items[0].due_at is not None
    assert result.life_items[0].due_at.day == 30
    assert {item.domain for item in result.life_items} == {"planning"}
    async with async_session() as db:
        updated = (await db.execute(select(IntakeEntry).where(IntakeEntry.source_session_id == session_id))).scalar_one()
    assert updated.status == "processed"
    assert updated.follow_up_questions_json == []


@pytest.mark.asyncio
async def test_agentic_capture_followup_answers_clarification_questions(monkeypatch):
    session_id = await _create_agent_session("intake-inbox")
    async with async_session() as db:
        entry = IntakeEntry(
            source="agent_capture",
            source_agent="intake-inbox",
            source_session_id=session_id,
            raw_text="organize paperwork",
            title="Organize paperwork",
            domain="planning",
            kind="idea",
            status="clarifying",
            follow_up_questions_json=["Which paperwork?", "By when?"],
        )
        db.add(entry)
        await db.commit()

    monkeypatch.setattr(
        "app.routers.life.chat_completion",
        AsyncMock(return_value='{"intent":"answer_questions","response":"Open questions:\\n- Which paperwork?\\n- By when?","actions":[]}'),
    )

    result = await capture_life(
        UnifiedCaptureRequest(
            message="what do i need to clarify?",
            session_id=session_id,
            new_session=False,
            route_hint="auto",
        )
    )

    assert result.route == "intake"
    assert "paperwork category" in result.response
    assert "deadline" in result.response
    assert result.life_items == []
    assert result.needs_answer_count == 2


@pytest.mark.asyncio
async def test_capture_v2_transcript_with_promise_memory_and_habit_creates_three_items(monkeypatch):
    fixed_now = datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr("app.routers.life.datetime", FrozenDateTime)

    async def _fake_split_capture_message(**_kwargs):
        return (
            [
                CaptureItemResponse(
                    type="reminder",
                    domain="work",
                    title="Send the client invoice",
                    summary="Invoice needs to go out tomorrow morning.",
                    source_span="I promised to send the client invoice tomorrow at 9am",
                    confidence=0.94,
                    due_at=datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc),
                    recurrence=None,
                    needs_follow_up=False,
                    follow_up_questions=[],
                    suggested_destination="life_item",
                ),
                CaptureItemResponse(
                    type="memory",
                    domain="work",
                    title="Client calls preference after Asr",
                    summary="User prefers client calls after Asr.",
                    source_span="remember that I prefer client calls after Asr",
                    confidence=0.86,
                    due_at=None,
                    recurrence=None,
                    needs_follow_up=False,
                    follow_up_questions=[],
                    suggested_destination="memory_review",
                ),
                CaptureItemResponse(
                    type="habit",
                    domain="health",
                    title="Restore nightly sleep routine",
                    summary="Bring back a stable nightly sleep routine.",
                    source_span="I want a nightly sleep routine again",
                    confidence=0.82,
                    due_at=None,
                    recurrence="nightly",
                    needs_follow_up=False,
                    follow_up_questions=[],
                    suggested_destination="life_item",
                ),
            ],
            [],
        )

    async def _fake_create_proposal(payload):
        return SimpleNamespace(
            id=77,
            source_agent=payload.agent_name,
            source_session_id=payload.session_id,
            scope=payload.scope,
            domain=payload.domain,
            title=payload.title,
            target_path="/vault/shared/work/client-calls.md",
            proposal_path="/vault/inbox/proposals/client-calls.md",
            expected_checksum=None,
            current_checksum=None,
            source_uri=payload.source_uri,
            conflict_reason="review_required",
            status="pending",
            proposed_content=payload.content,
            note_metadata_json={},
            created_at=fixed_now,
            applied_at=None,
        )

    monkeypatch.setattr("app.routers.life.split_capture_message", _fake_split_capture_message)
    monkeypatch.setattr("app.routers.life.create_shared_memory_review_proposal", _fake_create_proposal)

    result = await capture_life(
        UnifiedCaptureRequest(
            message=(
                "I promised to send the client invoice tomorrow at 9am, "
                "remember that I prefer client calls after Asr, and I want a nightly sleep routine again"
            ),
            source="discord_capture",
            timezone="UTC",
        )
    )

    assert result.route == "batch"
    assert result.raw_capture_id is not None
    assert len(result.captured_items) == 3
    assert [item.type for item in result.captured_items] == ["reminder", "memory", "habit"]
    assert len(result.routed_results) == 3
    assert len(result.life_items) == 2
    assert result.follow_up_job is not None
    assert result.follow_up_job.id is not None
    assert len(result.wiki_proposals) == 1
    assert result.wiki_proposals[0].title == "Client calls preference after Asr"
    assert result.needs_answer_count == 0


def test_unified_capture_family_message_has_domain_priority_and_detail_question():
    message = "Send message to my mother today at 5pm"

    assert _infer_commitment_domain(message) == "family"
    assert _detail_questions_for_capture(message, "family") == [
        "What should the message say, or what topic should it cover?"
    ]

    overrides = _priority_overrides_for_capture(message, None)
    assert overrides["domain"] == "family"
    assert overrides["priority"] == "medium"
    assert overrides["priority_score"] > 55


def test_commitment_title_cleaner_strips_uat_tags_and_remind_me_phrasing():
    assert _clean_commitment_title("UAT timezone: remind me tomorrow at 9am to check staging") == "check staging"
    assert _clean_commitment_title("UAT timezone: remind me Monday 4pm to check staging") == "check staging"


@pytest.mark.asyncio
async def test_commitment_due_inference_combines_weekday_and_followup_time(monkeypatch):
    fixed_now = datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.routers.life.datetime", SimpleNamespace(now=lambda _tz=None: fixed_now, min=datetime.min, combine=datetime.combine))

    due_at = await _infer_capture_due_at(
        "remind me to submit a request for tax return paper from hr on Monday\nFollow-up answer: create a case in workday before 4:50pm",
        None,
        "Africa/Casablanca",
    )

    assert due_at is not None
    assert due_at.day == 27
    assert due_at.hour == 15
    assert due_at.minute == 50


@pytest.mark.asyncio
async def test_capture_due_inference_uses_casablanca_for_relative_dates():
    fixed_now = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    cases = [
        ("tomorrow at 9am", datetime(2026, 4, 27, 8, 0)),
        ("tomorrow at 2pm", datetime(2026, 4, 27, 13, 0)),
        ("Monday 4pm", datetime(2026, 4, 27, 15, 0)),
        ("next Sunday 3rd May", datetime(2026, 5, 3, 8, 0)),
        ("Thursday", datetime(2026, 4, 30, 8, 0)),
        ("Saturday morning", datetime(2026, 5, 2, 8, 0)),
    ]

    for phrase, expected_utc in cases:
        due_at = await _infer_capture_due_at(phrase, None, "Africa/Casablanca", now_utc=fixed_now)
        assert due_at == expected_utc


@pytest.mark.asyncio
async def test_capture_followup_relative_dates_use_followup_timestamp():
    fixed_now = datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc)
    cases = [
        ("the deadline is at 2pm tomorrow", datetime(2026, 4, 28, 13, 0)),
        ("Monday 4pm", datetime(2026, 4, 27, 15, 0)),
        ("next Sunday 3rd May", datetime(2026, 5, 3, 8, 0)),
    ]

    for phrase, expected_utc in cases:
        due_at = await _infer_capture_due_at(phrase, None, "Africa/Casablanca", now_utc=fixed_now)
        assert due_at == expected_utc


def test_commitment_followup_note_tells_agent_to_merge_answers():
    note = _commitment_followup_note(
        SimpleNamespace(
            title="Submit tax return paper request",
            domain="work",
            kind="commitment",
            status="clarifying",
            raw_text="remind me to submit a request for tax return paper from hr on Monday",
            summary="Submit the request",
            desired_outcome=None,
            next_action=None,
            follow_up_questions_json=[
                "What method will you use to submit the request?",
                "Is there a specific time on Monday you aim to submit the request?",
            ],
        )
    )

    assert note is not None
    assert "follow-up answer" in note
    assert "status=ready" in note
    assert "Do not repeat" in note


@pytest.mark.asyncio
async def test_capture_v2_reminder_wording_creates_scheduled_job(monkeypatch):
    fixed_now = datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr("app.routers.life.datetime", FrozenDateTime)
    monkeypatch.setattr(
        "app.routers.life.split_capture_message",
        AsyncMock(
            return_value=(
                [
                    CaptureItemResponse(
                        type="reminder",
                        domain="work",
                        title="Submit tax return request",
                        summary="Submit the HR tax return request before Monday 4:30pm.",
                        source_span="remind me to submit the tax return request from hr on Monday before 4:30pm",
                        confidence=0.93,
                        due_at=datetime(2026, 4, 27, 15, 30, tzinfo=timezone.utc),
                        recurrence=None,
                        needs_follow_up=False,
                        follow_up_questions=[],
                        suggested_destination="life_item",
                    )
                ],
                [],
            )
        ),
    )

    result = await capture_life(
        UnifiedCaptureRequest(
            message="remind me to submit the tax return request from hr on Monday before 4:30pm",
            source="discord_capture",
            timezone="UTC",
        )
    )

    assert result.route == "commitment"
    assert len(result.life_items) == 1
    assert result.follow_up_job is not None
    assert result.follow_up_job.id is not None
    assert result.routed_results[0].destination == "life_item"


@pytest.mark.asyncio
async def test_capture_v2_remember_that_creates_memory_review(monkeypatch):
    async def _fake_create_proposal(payload):
        return SimpleNamespace(
            id=55,
            source_agent=payload.agent_name,
            source_session_id=payload.session_id,
            scope=payload.scope,
            domain=payload.domain,
            title=payload.title,
            target_path="/vault/shared/health/morning-sunlight.md",
            proposal_path="/vault/inbox/proposals/morning-sunlight.md",
            expected_checksum=None,
            current_checksum=None,
            source_uri=payload.source_uri,
            conflict_reason="review_required",
            status="pending",
            proposed_content=payload.content,
            note_metadata_json={},
            created_at=datetime.now(timezone.utc),
            applied_at=None,
        )

    monkeypatch.setattr(
        "app.routers.life.split_capture_message",
        AsyncMock(
            return_value=(
                [
                    CaptureItemResponse(
                        type="memory",
                        domain="health",
                        title="Morning sunlight helps reset energy",
                        summary="User wants morning sunlight remembered as a reliable energy reset.",
                        source_span="remember that morning sunlight helps reset my energy",
                        confidence=0.88,
                        due_at=None,
                        recurrence=None,
                        needs_follow_up=False,
                        follow_up_questions=[],
                        suggested_destination="memory_review",
                    )
                ],
                [],
            )
        ),
    )
    monkeypatch.setattr("app.routers.life.create_shared_memory_review_proposal", _fake_create_proposal)

    result = await capture_life(
        UnifiedCaptureRequest(
            message="remember that morning sunlight helps reset my energy",
            source="discord_capture",
        )
    )

    assert result.route == "memory"
    assert len(result.wiki_proposals) == 1
    assert result.wiki_proposals[0].id == 55
    assert result.routed_results[0].destination == "memory_review"


@pytest.mark.asyncio
async def test_capture_v2_daily_log_updates_scorecard_and_prayer_checkin(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value=_fake_schedule()))
    monkeypatch.setattr("app.routers.life.get_today_schedule", AsyncMock(return_value={"date": "2026-03-03", **_fake_schedule()}))
    prayer_checkin = AsyncMock(
        return_value={
            "prayer_date": "2026-03-03",
            "prayer_name": "Asr",
            "status_raw": "on_time",
            "status_scored": "on_time",
            "is_retroactive": True,
            "reported_at_utc": datetime(2026, 3, 3, 16, 0, tzinfo=timezone.utc),
        }
    )
    monkeypatch.setattr("app.routers.life.log_prayer_checkin_retroactive", prayer_checkin)
    monkeypatch.setattr(
        "app.routers.life.split_capture_message",
        AsyncMock(
            return_value=(
                [
                    CaptureItemResponse(
                        type="daily_log",
                        domain="health",
                        title="Sleep log",
                        summary="Slept 7h with bedtime and wake time.",
                        source_span="slept 7h bedtime 23:40 wake 07:10",
                        confidence=0.92,
                        due_at=None,
                        recurrence=None,
                        needs_follow_up=False,
                        follow_up_questions=[],
                        suggested_destination="daily_log",
                    ),
                    CaptureItemResponse(
                        type="daily_log",
                        domain="health",
                        title="Meal log",
                        summary="Meal completed.",
                        source_span="meal done",
                        confidence=0.92,
                        due_at=None,
                        recurrence=None,
                        needs_follow_up=False,
                        follow_up_questions=[],
                        suggested_destination="daily_log",
                    ),
                    CaptureItemResponse(
                        type="daily_log",
                        domain="health",
                        title="Training log",
                        summary="Training completed.",
                        source_span="training done",
                        confidence=0.92,
                        due_at=None,
                        recurrence=None,
                        needs_follow_up=False,
                        follow_up_questions=[],
                        suggested_destination="daily_log",
                    ),
                    CaptureItemResponse(
                        type="daily_log",
                        domain="deen",
                        title="Prayer log",
                        summary="Asr prayed on time.",
                        source_span="prayed Asr on time",
                        confidence=0.92,
                        due_at=None,
                        recurrence=None,
                        needs_follow_up=False,
                        follow_up_questions=[],
                        suggested_destination="daily_log",
                    ),
                ],
                [],
            )
        ),
    )

    result = await capture_life(
        UnifiedCaptureRequest(
            message="slept 7h bedtime 23:40 wake 07:10, meal done, training done, prayed Asr on time",
            source="discord_capture",
        )
    )

    assert result.route == "batch"
    assert len(result.captured_items) == 4
    assert set(result.logged_signals) >= {"sleep", "meal", "training:done", "prayer:asr:on_time"}
    prayer_checkin.assert_awaited_once()

    agenda = await get_today_agenda()
    assert agenda["scorecard"].sleep_hours == 7
    assert agenda["scorecard"].meals_count == 1
    assert agenda["scorecard"].training_status == "done"


@pytest.mark.asyncio
async def test_capture_v2_ambiguous_item_asks_followup_and_keeps_raw_capture(monkeypatch):
    monkeypatch.setattr(
        "app.routers.life.split_capture_message",
        AsyncMock(
            return_value=(
                [
                    CaptureItemResponse(
                        type="idea",
                        domain="work",
                        title="Admin thing with HR",
                        summary="Something admin-related needs handling with HR next week.",
                        source_span="sort out the admin thing with HR maybe sometime next week",
                        confidence=0.34,
                        due_at=None,
                        recurrence=None,
                        needs_follow_up=True,
                        follow_up_questions=["What exact HR task should LifeOS track?"],
                        suggested_destination="needs_answer",
                    )
                ],
                [],
            )
        ),
    )

    result = await capture_life(
        UnifiedCaptureRequest(
            message="sort out the admin thing with HR maybe sometime next week",
            source="discord_capture",
        )
    )

    assert result.raw_capture_id is not None
    assert result.needs_answer_count == 1
    assert result.entries[0].status == "clarifying"
    assert result.entries[0].follow_up_questions == ["What exact HR task should LifeOS track?"]
    async with async_session() as db:
        raw_capture = await db.get(ContextEvent, result.raw_capture_id)
    assert raw_capture is not None
    assert "admin thing with HR" in raw_capture.raw_text


@pytest.mark.asyncio
async def test_capture_v2_residue_surfaces_meaningful_fragment_when_model_misses_it(monkeypatch):
    monkeypatch.setattr(
        "app.services.capture_v2.chat_completion",
        AsyncMock(
            return_value=(
                '{"captured_items":['
                '{"type":"reminder","domain":"work","title":"Send invoice","summary":"Invoice reminder.",'
                '"source_span":"send invoice tomorrow at 9am","confidence":0.95,'
                '"due_at":"2026-04-27T09:00:00Z","recurrence":null,"needs_follow_up":false,'
                '"follow_up_questions":[],"suggested_destination":"life_item"}'
                '],"uncaptured_residue":[]}'
            )
        ),
    )

    items, residue = await split_capture_message(
        message="send invoice tomorrow at 9am and remember that I prefer morning focus blocks",
        timezone_name="UTC",
        route_hint="auto",
    )

    assert len(items) == 1
    assert residue
    assert any("morning focus" in fragment.lower() or "remember" in fragment.lower() for fragment in residue)
