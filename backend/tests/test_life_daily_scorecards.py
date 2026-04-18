from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import DailyLogCreate, ProfileUpdate
from app.services.life import log_daily_signal
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
