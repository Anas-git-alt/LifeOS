from __future__ import annotations

from datetime import datetime, timezone
import pytest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.database import async_session
from app.models import Agent, ChatSession, CommitmentCaptureResponse, IntakeCaptureResponse, IntakeEntry, LifeItemCreate, UnifiedCaptureRequest
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
from app.services.life import create_life_item, get_today_agenda


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
async def test_unified_capture_commitment_facade(monkeypatch):
    async def _fake_capture_commitment(data):
        assert data.message == "Send invoice tomorrow at 9am"
        assert data.source == "webui_today_capture"
        assert data.due_at is not None
        assert data.due_at.hour == 9
        assert data.due_at.minute == 0
        return CommitmentCaptureResponse(
            response="Tracked.",
            auto_promoted=True,
            needs_follow_up=False,
        )

    monkeypatch.setattr("app.routers.life.capture_commitment", _fake_capture_commitment)

    result = await capture_life(
        UnifiedCaptureRequest(
            message="Send invoice tomorrow at 9am",
            source="webui_today_capture",
            timezone="UTC",
        )
    )

    assert result.route == "commitment"
    assert result.response == "Tracked."
    assert result.auto_promoted_count == 1


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
async def test_unified_capture_intake_facade(monkeypatch):
    async def _fake_capture_inbox(data):
        assert data.message == "I want to build better sleep habits"
        assert data.source == "webui_today_capture"
        return IntakeCaptureResponse(
            response="Captured.",
            entries=[],
            life_items=[],
            wiki_proposals=[],
            auto_promoted_count=0,
        )

    monkeypatch.setattr("app.routers.life.capture_inbox", _fake_capture_inbox)

    result = await capture_life(
        UnifiedCaptureRequest(
            message="I want to build better sleep habits",
            source="webui_today_capture",
        )
    )

    assert result.route == "intake"
    assert result.response == "Captured."


@pytest.mark.asyncio
async def test_unified_capture_status_update_logs_and_closes_family_message(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value=_fake_schedule()))
    item = await create_life_item(
        LifeItemCreate(
            domain="family",
            title="Send message to mother",
            kind="task",
            priority="high",
            priority_score=90,
        )
    )
    async with async_session() as db:
        entry = IntakeEntry(
            source="agent_capture",
            source_agent="commitment-capture",
            raw_text="Send message to my mother today at 5pm",
            title="Send message to mother",
            domain="family",
            kind="commitment",
            status="clarifying",
            follow_up_questions_json=["What should the message say?"],
            linked_life_item_id=item.id,
        )
        db.add(entry)
        await db.commit()

    result = await capture_life(
        UnifiedCaptureRequest(
            message="Message sent to ask about her health, meal i ate a sandwitch, and i drank 1 cup of water",
            source="discord_capture",
        )
    )

    assert result.route == "daily_log"
    assert result.completed_items[0].id == item.id
    assert set(result.logged_signals) >= {"completed family message", "family", "meal", "hydration x1", "priority"}

    agenda = await get_today_agenda()
    assert agenda["scorecard"].family_action_done is True
    assert agenda["scorecard"].meals_count == 1
    assert agenda["scorecard"].hydration_count == 1
    assert agenda["scorecard"].top_priority_completed_count == 1
    assert all(row.id != item.id for row in agenda["top_focus"])
    async with async_session() as db:
        entry_result = await db.execute(select(IntakeEntry).where(IntakeEntry.linked_life_item_id == item.id))
        updated_entry = entry_result.scalar_one()
    assert updated_entry.status == "processed"
    assert updated_entry.follow_up_questions_json == []

    duplicate = await capture_life(
        UnifiedCaptureRequest(
            message="Message sent to ask about her health, meal i ate a sandwitch, and i drank 1 cup of water",
            source="discord_capture",
        )
    )
    assert duplicate.route == "daily_log"
    assert duplicate.entries == []
    agenda_after_duplicate = await get_today_agenda()
    assert agenda_after_duplicate["scorecard"].meals_count == 1
    assert agenda_after_duplicate["scorecard"].hydration_count == 1
    assert agenda_after_duplicate["scorecard"].top_priority_completed_count == 1
