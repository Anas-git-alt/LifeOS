from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import DailyLogCreate, ProfileUpdate
from app.services.life import get_today_agenda, log_daily_signal
from app.services.profile import update_profile


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


def _fake_schedule():
    return {
        "date": "2026-03-03",
        "timezone": "Africa/Casablanca",
        "city": "Casablanca",
        "country": "Morocco",
        "hijri_month": 9,
        "is_ramadan": True,
        "next_prayer": "Asr",
        "windows": [
            {
                "prayer_name": "Asr",
                "starts_at": datetime(2026, 3, 3, 15, 30, tzinfo=timezone.utc),
                "ends_at": datetime(2026, 3, 3, 18, 45, tzinfo=timezone.utc),
            }
        ],
    }


def _freeze_life_datetime(monkeypatch, frozen_at: datetime):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_at if tz is None else frozen_at.astimezone(tz)

    monkeypatch.setattr("app.services.life.datetime", FrozenDateTime)


def test_daily_log_api_updates_scorecard_and_today_payload(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value=_fake_schedule()))

    with TestClient(app) as client:
        overdue_resp = client.post(
            "/api/life/items",
            headers=_headers(),
            json={
                "domain": "work",
                "title": "Send invoice",
                "kind": "task",
                "priority": "high",
                "due_at": (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat(),
            },
        )
        assert overdue_resp.status_code == 200

        log_resp = client.post(
            "/api/life/daily-log",
            headers=_headers(),
            json={"kind": "hydration", "count": 2},
        )
        assert log_resp.status_code == 200
        log_payload = log_resp.json()
        assert log_payload["kind"] == "hydration"
        assert "water 2" in log_payload["message"]
        assert log_payload["scorecard"]["hydration_count"] == 2

        today_resp = client.get("/api/life/today", headers=_headers())
        assert today_resp.status_code == 200
        today_payload = today_resp.json()
        assert today_payload["scorecard"]["hydration_count"] == 2
        assert today_payload["next_prayer"]["name"] == "Asr"
        assert today_payload["rescue_plan"]["status"] in {"watch", "rescue"}
        assert today_payload["sleep_protocol"]["bedtime_target"] == "23:30"
        assert isinstance(today_payload["streaks"], list)
        assert today_payload["trend_summary"]["window_days"] == 7
        assert isinstance(today_payload["top_focus"], list)
        assert isinstance(today_payload["due_today"], list)
        assert isinstance(today_payload["overdue"], list)
        assert isinstance(today_payload["ready_intake"], list)


@pytest.mark.asyncio
async def test_daily_log_uses_local_profile_day(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 3, 3, 12, 30, tzinfo=timezone.utc)
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr("app.services.life.datetime", FrozenDateTime)
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value=_fake_schedule()))
    monkeypatch.setattr(
        "app.services.life._load_open_items_snapshot",
        AsyncMock(return_value={"open_items": [], "top_focus": [], "due_today": [], "overdue": [], "domain_summary": {}}),
    )

    await update_profile(ProfileUpdate(timezone="Pacific/Kiritimati"))
    result = await log_daily_signal(DailyLogCreate(kind="hydration", count=1))

    assert result["scorecard"].local_date.isoformat() == "2026-03-04"
    assert result["scorecard"].hydration_count == 1


@pytest.mark.asyncio
async def test_today_summary_includes_streaks_and_completed_day_trends(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value=_fake_schedule()))
    monkeypatch.setattr("app.services.life.get_data_start_date", AsyncMock(return_value=datetime(2026, 3, 1).date()))
    monkeypatch.setattr(
        "app.services.life._load_open_items_snapshot",
        AsyncMock(return_value={"open_items": [], "top_focus": [], "due_today": [], "overdue": [], "domain_summary": {}}),
    )

    await update_profile(ProfileUpdate(timezone="UTC"))

    _freeze_life_datetime(monkeypatch, datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc))
    await log_daily_signal(DailyLogCreate(kind="sleep", hours=7.5))
    await log_daily_signal(DailyLogCreate(kind="meal", count=1, protein_hit=True))
    await log_daily_signal(DailyLogCreate(kind="hydration", count=2))
    await log_daily_signal(DailyLogCreate(kind="training", status="done"))
    await log_daily_signal(DailyLogCreate(kind="family", done=True))
    await log_daily_signal(DailyLogCreate(kind="priority", count=1))
    await log_daily_signal(DailyLogCreate(kind="shutdown", done=True))

    _freeze_life_datetime(monkeypatch, datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc))
    await log_daily_signal(DailyLogCreate(kind="sleep", hours=7.25))
    await log_daily_signal(DailyLogCreate(kind="meal", count=1, protein_hit=True))
    await log_daily_signal(DailyLogCreate(kind="hydration", count=2))
    await log_daily_signal(DailyLogCreate(kind="training", status="rest"))
    await log_daily_signal(DailyLogCreate(kind="family", done=True))
    await log_daily_signal(DailyLogCreate(kind="priority", count=1))
    await log_daily_signal(DailyLogCreate(kind="shutdown", done=True))

    _freeze_life_datetime(monkeypatch, datetime(2026, 3, 3, 10, 30, tzinfo=timezone.utc))
    await log_daily_signal(DailyLogCreate(kind="sleep", hours=7.0))

    summary = await get_today_agenda()
    sleep_streak = next(item for item in summary["streaks"] if item["key"] == "sleep")
    hydration_streak = next(item for item in summary["streaks"] if item["key"] == "hydration")

    assert sleep_streak["today_status"] == "hit"
    assert sleep_streak["current_streak"] == 3
    assert hydration_streak["today_status"] == "pending"
    assert hydration_streak["current_streak"] == 2
    assert hydration_streak["hits_last_7"] == 2

    trend_summary = summary["trend_summary"]
    assert trend_summary["average_completion_pct"] == 100
    assert [day["date"].isoformat() for day in trend_summary["recent_days"]] == ["2026-03-01", "2026-03-02"]
    assert trend_summary["best_day"]["completion_pct"] == 100


@pytest.mark.asyncio
async def test_today_summary_includes_sleep_protocol_targets_and_logged_sleep(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value=_fake_schedule()))
    monkeypatch.setattr("app.services.life.get_data_start_date", AsyncMock(return_value=datetime(2026, 3, 3).date()))
    monkeypatch.setattr(
        "app.services.life._load_open_items_snapshot",
        AsyncMock(return_value={"open_items": [], "top_focus": [], "due_today": [], "overdue": [], "domain_summary": {}}),
    )

    await update_profile(
        ProfileUpdate(
            timezone="UTC",
            sleep_bedtime_target="23:00",
            sleep_wake_target="07:00",
            sleep_caffeine_cutoff="14:00",
            sleep_wind_down_checklist=["Dim lights", "Prep clothes"],
        )
    )

    _freeze_life_datetime(monkeypatch, datetime(2026, 3, 3, 9, 15, tzinfo=timezone.utc))
    result = await log_daily_signal(
        DailyLogCreate(kind="sleep", hours=8, bedtime="23:05", wake_time="07:10", note="solid night")
    )

    protocol = result["sleep_protocol"]
    assert protocol["bedtime_target"] == "23:00"
    assert protocol["wake_target"] == "07:00"
    assert protocol["caffeine_cutoff"] == "14:00"
    assert protocol["wind_down_checklist"] == ["Dim lights", "Prep clothes"]
    assert protocol["sleep_hours_logged"] == 8
    assert protocol["bedtime_logged"] == "23:05"
    assert protocol["wake_time_logged"] == "07:10"

    summary = await get_today_agenda()
    assert summary["sleep_protocol"]["bedtime_target"] == "23:00"
    assert summary["sleep_protocol"]["wake_time_logged"] == "07:10"
