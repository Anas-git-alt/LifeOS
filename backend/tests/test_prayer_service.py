"""Prayer service unit tests."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.prayer_service import _choose_scored_status, _parse_hhmm
from app.models import PrayerRetroactiveCheckinRequest


def test_parse_hhmm_with_suffix():
    parsed = _parse_hhmm("05:41 (+01)")
    assert parsed.hour == 5
    assert parsed.minute == 41


def test_retroactive_on_time_downgraded_to_late():
    assert _choose_scored_status("on_time", is_retroactive=True) == "late"


def test_non_retroactive_keeps_status():
    assert _choose_scored_status("on_time", is_retroactive=False) == "on_time"
    assert _choose_scored_status("late", is_retroactive=False) == "late"
    assert _choose_scored_status("missed", is_retroactive=False) == "missed"


@pytest.mark.asyncio
async def test_auto_close_marks_expired_prayer_missed(monkeypatch):
    added = []

    class _FakeScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return _FakeScalarResult(self._rows)

    class _FakeSession:
        def __init__(self, rows):
            self.rows = rows
            self.commit = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _statement):
            return _FakeResult(self.rows)

        def add(self, row):
            added.append(row)

    window = SimpleNamespace(
        id=7,
        local_date=date(2026, 4, 11),
        prayer_name="Asr",
        ends_at_utc=datetime(2026, 4, 11, 15, 30, 0),
    )
    fake_session = _FakeSession([window])
    publish_event = AsyncMock()

    monkeypatch.setattr("app.services.prayer_service.async_session", lambda: fake_session)
    monkeypatch.setattr("app.services.prayer_service.publish_event", publish_event)

    from app.services.prayer_service import auto_mark_unknown_expired

    closed = await auto_mark_unknown_expired()

    assert closed == 1
    assert len(added) == 1
    assert added[0].status_raw == "missed"
    assert added[0].status_scored == "missed"
    assert added[0].source == "system_autoclose"
    publish_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_webui_retroactive_edit_tagged_as_webui_state_change(monkeypatch):
    window = SimpleNamespace(id=42)
    upsert = AsyncMock(
        return_value=SimpleNamespace(
            status_raw="on_time",
            status_scored="late",
            is_retroactive=True,
            reported_at_utc=datetime(2026, 4, 11, 18, 0, 0),
        )
    )

    monkeypatch.setattr("app.services.prayer_service._get_window_or_raise", AsyncMock(return_value=window))
    monkeypatch.setattr("app.services.prayer_service._upsert_checkin", upsert)
    monkeypatch.setattr("app.services.prayer_service.publish_event", AsyncMock())

    from app.services.prayer_service import log_prayer_checkin_retroactive

    await log_prayer_checkin_retroactive(
        PrayerRetroactiveCheckinRequest(
            prayer_date="2026-04-11",
            prayer_name="Asr",
            status="on_time",
            source="webui_dashboard",
        )
    )

    assert upsert.await_args.kwargs["retro_reason"] == "webui_state_change"
