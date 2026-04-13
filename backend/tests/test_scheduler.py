"""Scheduler helper tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apscheduler.triggers.date import DateTrigger

from app.services.scheduler import _parse_cadence, run_persistent_job, sync_persistent_job


class _FakeScheduler:
    def __init__(self):
        self.jobs: dict[str, SimpleNamespace] = {}

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def add_job(self, _func, *, trigger, id, kwargs, replace_existing, coalesce, max_instances, misfire_grace_time):
        self.jobs[id] = SimpleNamespace(
            id=id,
            trigger=trigger,
            kwargs=kwargs,
            replace_existing=replace_existing,
            coalesce=coalesce,
            max_instances=max_instances,
            misfire_grace_time=misfire_grace_time,
            next_run_time=getattr(trigger, "run_date", None),
        )

    def remove_job(self, job_id: str):
        self.jobs.pop(job_id, None)


def test_parse_cadence_daily():
    minute, hour, dow = _parse_cadence("0 8 *")
    assert minute == "0"
    assert hour == "8"
    assert dow == "*"


def test_parse_cadence_with_list_hours():
    minute, hour, dow = _parse_cadence("0 4,12,15,18,20 *")
    assert minute == "0"
    assert hour == "4,12,15,18,20"
    assert dow == "*"


@pytest.mark.asyncio
async def test_sync_persistent_job_uses_date_trigger_for_once_jobs(monkeypatch):
    fake_scheduler = _FakeScheduler()
    future_run_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(tzinfo=None)
    row = SimpleNamespace(
        id=9,
        name="One-time review",
        enabled=True,
        paused=False,
        schedule_type="once",
        run_at=future_run_at,
        completed_at=None,
        timezone="Africa/Casablanca",
        cron_expression=None,
    )
    monkeypatch.setattr("app.services.scheduler.scheduler", fake_scheduler)
    monkeypatch.setattr("app.services.scheduler.get_job", AsyncMock(return_value=row))
    monkeypatch.setattr("app.services.scheduler._update_job_next_run", AsyncMock())
    monkeypatch.setattr("app.services.scheduler.record_job_run", AsyncMock())

    await sync_persistent_job(9)

    scheduled = fake_scheduler.get_job("scheduled_job_9")
    assert scheduled is not None
    assert isinstance(scheduled.trigger, DateTrigger)


@pytest.mark.asyncio
async def test_sync_persistent_job_marks_expired_once_jobs_missed(monkeypatch):
    fake_scheduler = _FakeScheduler()
    row = SimpleNamespace(
        id=13,
        name="Expired once job",
        enabled=True,
        paused=False,
        schedule_type="once",
        run_at=(datetime.now(timezone.utc) - timedelta(minutes=20)).replace(tzinfo=None),
        completed_at=None,
        timezone="Africa/Casablanca",
        cron_expression=None,
    )
    record_job_run = AsyncMock()
    monkeypatch.setattr("app.services.scheduler.scheduler", fake_scheduler)
    monkeypatch.setattr("app.services.scheduler.get_job", AsyncMock(return_value=row))
    monkeypatch.setattr("app.services.scheduler.record_job_run", record_job_run)
    monkeypatch.setattr("app.services.scheduler._update_job_next_run", AsyncMock())

    await sync_persistent_job(13)

    record_job_run.assert_awaited()
    assert record_job_run.await_args.kwargs["status"] == "missed"
    assert record_job_run.await_args.kwargs["enabled"] is False


@pytest.mark.asyncio
async def test_run_persistent_job_respects_silent_once_job_delivery(monkeypatch):
    row = SimpleNamespace(
        id=27,
        enabled=True,
        paused=False,
        schedule_type="once",
        job_type="agent_nudge",
        agent_name="sandbox",
        prompt_template="Review the note.",
        target_channel="planning",
        target_channel_id="123456789012345678",
        notification_mode="silent",
    )
    fake_scheduler = _FakeScheduler()
    record_job_run = AsyncMock()
    run_scheduled_agent = AsyncMock(return_value={"status": "completed", "delivered": False})

    monkeypatch.setattr("app.services.scheduler.scheduler", fake_scheduler)
    monkeypatch.setattr("app.services.scheduler.get_job", AsyncMock(return_value=row))
    monkeypatch.setattr("app.services.scheduler.record_job_run", record_job_run)
    monkeypatch.setattr("app.services.scheduler.run_scheduled_agent", run_scheduled_agent)

    await run_persistent_job(27)

    run_scheduled_agent.assert_awaited_with(
        agent_name="sandbox",
        prompt_override="Review the note.",
        target_channel_override="planning",
        target_channel_id_override="123456789012345678",
        notification_mode_override="silent",
    )
    assert record_job_run.await_args.kwargs["enabled"] is False
    assert record_job_run.await_args.kwargs["completed_at"] is not None
