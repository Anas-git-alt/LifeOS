from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.database import async_session
from app.models import ActionStatus, Agent, DailyScorecard, PendingAction, ProfileUpdate
from app.services.action_executor import execute_pending_action
from app.services.daily_log_proposals import propose_daily_log_payload
from app.services.orchestrator import handle_message
from app.services.profile import update_profile


def _fake_schedule():
    return {
        "date": "2026-03-03",
        "timezone": "UTC",
        "city": "Casablanca",
        "country": "Morocco",
        "hijri_month": 9,
        "is_ramadan": True,
        "next_prayer": "Isha",
        "windows": [],
    }


def _freeze_life_datetime(monkeypatch, frozen_at: datetime):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_at if tz is None else frozen_at.astimezone(tz)

    monkeypatch.setattr("app.services.life.datetime", FrozenDateTime)


@pytest.mark.asyncio
async def test_daily_log_proposal_extracts_meal_and_hydration_without_provider():
    payload = await propose_daily_log_payload("i drank water, and ate half a shawarma")

    assert payload is not None
    assert payload["logs"] == [
        {"kind": "hydration", "count": 1, "note": "i drank water, and ate half a shawarma"},
        {
            "kind": "meal",
            "count": 1,
            "note": "i drank water, and ate half a shawarma",
            "protein_hit": False,
        },
    ]


@pytest.mark.asyncio
async def test_daily_log_proposal_ignores_advice_question():
    payload = await propose_daily_log_payload("should I drink water before bed?")

    assert payload is None


@pytest.mark.asyncio
async def test_daily_log_batch_pending_action_executes_logs(monkeypatch):
    _freeze_life_datetime(monkeypatch, datetime(2026, 3, 3, 20, 0, tzinfo=timezone.utc))
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value=_fake_schedule()))
    monkeypatch.setattr(
        "app.services.life._load_open_items_snapshot",
        AsyncMock(return_value={"open_items": [], "top_focus": [], "due_today": [], "overdue": [], "domain_summary": {}}),
    )
    await update_profile(ProfileUpdate(timezone="UTC"))

    action = PendingAction(
        agent_name="sandbox",
        action_type="daily_log_batch",
        summary="Proposed daily log",
        details=json.dumps(
            {
                "logs": [
                    {"kind": "hydration", "count": 1, "note": "drank water"},
                    {"kind": "meal", "count": 1, "note": "ate shawarma"},
                ]
            }
        ),
        status=ActionStatus.PENDING,
    )

    ok, message = await execute_pending_action(action)

    assert ok is True
    assert "Logged:" in message
    async with async_session() as db:
        result = await db.execute(select(DailyScorecard))
        scorecard = result.scalar_one()
    assert scorecard.hydration_count == 1
    assert scorecard.meals_count == 1


@pytest.mark.asyncio
async def test_agent_chat_creates_confirmable_daily_log_action(monkeypatch):
    monkeypatch.setattr(
        "app.services.orchestrator.build_agent_state_packet",
        AsyncMock(return_value={"grounded": True, "strict": True, "sources": ["today"], "warnings": []}),
    )
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.orchestrator.publish_event", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.services.daily_log_proposals.chat_completion",
        AsyncMock(return_value='{"logs":[{"kind":"hydration","count":1},{"kind":"meal","count":1}]}'),
    )
    async with async_session() as db:
        db.add(Agent(name="sandbox", provider="test", model="test", system_prompt="test", enabled=True))
        await db.commit()

    result = await handle_message(
        agent_name="sandbox",
        user_message="i drank water, and ate half a shawarma",
        session_enabled=False,
    )

    assert result["pending_action_type"] == "daily_log_batch"
    assert result["pending_action_id"]
    assert "React with" in result["response"]
    async with async_session() as db:
        row = await db.get(PendingAction, result["pending_action_id"])
    assert row is not None
    assert row.action_type == "daily_log_batch"
    assert row.status == ActionStatus.PENDING
