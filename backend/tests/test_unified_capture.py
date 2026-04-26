from __future__ import annotations

from datetime import datetime, timezone
import pytest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.database import async_session
from app.models import CommitmentCaptureResponse, IntakeCaptureResponse, IntakeEntry, LifeItemCreate, UnifiedCaptureRequest
from app.routers.life import (
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


def test_unified_capture_route_selector_sorts_common_inputs():
    assert _select_capture_route(UnifiedCaptureRequest(message="Send invoice tomorrow at 9am")) == "commitment"
    assert _select_capture_route(UnifiedCaptureRequest(message="Meeting notes: decided to keep one capture inbox")) == "memory"
    assert _select_capture_route(UnifiedCaptureRequest(message="I want to build better sleep habits")) == "intake"


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
