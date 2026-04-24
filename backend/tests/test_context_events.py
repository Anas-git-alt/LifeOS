from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.main import app
from app.models import ContextEvent, JobRunLog, LifeCheckin, LifeItem, ScheduledJobCreate
from app.services.context_events import capture_job_reply, run_no_reply_followups
from app.services.jobs import create_job, record_job_run
from app.services.vault import obsidian_vault_root


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


def test_meeting_intake_creates_review_proposal_and_apply_writes_note(monkeypatch):
    monkeypatch.setattr(
        "app.services.shared_memory.openviking_client.search",
        AsyncMock(return_value=type("Result", (), {"resources": [], "memories": [], "skills": []})()),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/memory/intake/meeting",
            headers=_headers(),
            json={
                "title": "Client Planning Sync",
                "domain": "work",
                "summary": "Decision: build the Obsidian wiki slowly. Action: create the first shared context note.",
                "source": "test",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["event"]["status"] == "curated"
        assert payload["proposals"][0]["conflict_reason"] == "review_required"
        target_path = payload["proposals"][0]["target_path"]
        assert not Path(target_path).exists()

        conflicts = client.get("/api/vault/conflicts", headers=_headers())
        assert conflicts.status_code == 200
        assert any(row["id"] == payload["proposals"][0]["id"] for row in conflicts.json())

        apply_resp = client.post(
            f"/api/memory/proposals/{payload['proposals'][0]['id']}/apply",
            headers=_headers(),
            json={"source_agent": "webui"},
        )
        assert apply_resp.status_code == 200
        assert apply_resp.json()["status"] == "applied"
        assert obsidian_vault_root().joinpath("shared/domains/work/client-planning-sync.md").exists()
        assert "client-planning-sync" in obsidian_vault_root().joinpath("shared/domains/work/index.md").read_text()


@pytest.mark.asyncio
async def test_job_run_records_notification_reply_deadline():
    job = await create_job(
        ScheduledJobCreate(
            name="Reply expected",
            agent_name="sandbox",
            schedule_type="cron",
            cron_expression="30 7 * * mon-fri",
            notification_mode="channel",
            target_channel="planning",
            expect_reply=True,
            follow_up_after_minutes=30,
        )
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await record_job_run(
        job_id=job.id,
        started_at=now,
        finished_at=now,
        status="delivered",
        message="ok",
        error=None,
        last_run_at=now,
        next_run_at=None,
        notification_channel="planning",
        notification_channel_id="123",
        notification_message_id="456",
        awaiting_reply_until=now + timedelta(minutes=30),
    )
    async with async_session() as db:
        run = (await db.execute(select(JobRunLog).where(JobRunLog.job_id == job.id))).scalar_one()
    assert run.notification_message_id == "456"
    assert run.awaiting_reply_until is not None
    assert run.reply_count == 0


@pytest.mark.asyncio
async def test_capture_job_reply_publishes_realtime_update(monkeypatch):
    publish_event = AsyncMock()
    monkeypatch.setattr("app.services.context_events.publish_event", publish_event)
    monkeypatch.setattr(
        "app.services.context_events.curate_context_event",
        AsyncMock(side_effect=lambda event_id: (type("Event", (), {"id": event_id})(), [], [])),
    )

    job = await create_job(
        ScheduledJobCreate(
            name="Reply ack",
            agent_name="sandbox",
            schedule_type="once",
            run_at=datetime.now(timezone.utc) + timedelta(hours=1),
            notification_mode="channel",
            target_channel="planning",
            expect_reply=True,
        )
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await record_job_run(
        job_id=job.id,
        started_at=now,
        finished_at=now,
        status="delivered",
        message="ok",
        error=None,
        last_run_at=now,
        next_run_at=None,
        notification_channel="planning",
        notification_channel_id="123",
        notification_message_id="abc123",
        awaiting_reply_until=now + timedelta(minutes=10),
    )

    payload = type(
        "ReplyPayload",
        (),
        {
            "notification_message_id": "abc123",
            "reply_text": "checking in",
            "discord_channel_id": "123",
            "discord_reply_message_id": "reply-1",
            "discord_user_id": "42",
            "source": "discord_reply",
        },
    )()
    await capture_job_reply(payload)
    assert publish_event.await_count >= 1
    assert any(call.args[0] == "jobs.run.updated" for call in publish_event.await_args_list)


def test_job_reply_links_run_creates_event_and_commitment_checkin():
    async def _seed():
        async with async_session() as db:
            item = LifeItem(domain="work", kind="task", title="Send invoice", status="open")
            db.add(item)
            await db.flush()
            item_id = item.id
            await db.commit()
        job = await create_job(
            ScheduledJobCreate(
                name="Commitment follow-up #1",
                agent_name="commitment-coach",
                schedule_type="once",
                run_at=datetime.now(timezone.utc) + timedelta(hours=1),
                notification_mode="channel",
                target_channel="planning",
                source="commitment_follow_up",
                config_json={"origin": "commitment_capture", "life_item_id": item_id},
            )
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await record_job_run(
            job_id=job.id,
            started_at=now,
            finished_at=now,
            status="delivered",
            message="ok",
            error=None,
            last_run_at=now,
            next_run_at=None,
            notification_channel="planning",
            notification_channel_id="123",
            notification_message_id="999",
            awaiting_reply_until=now + timedelta(minutes=120),
        )
        return item_id

    import asyncio

    item_id = asyncio.run(_seed())
    with TestClient(app) as client:
        response = client.post(
            "/api/memory/intake/job-reply",
            headers=_headers(),
            json={
                "notification_message_id": "999",
                "reply_text": "Done, invoice sent.",
                "discord_channel_id": "123",
                "discord_reply_message_id": "1000",
                "discord_user_id": "42",
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["life_checkin_result"] == "done"

    async def _assert_db():
        async with async_session() as db:
            run = (await db.execute(select(JobRunLog).where(JobRunLog.notification_message_id == "999"))).scalar_one()
            event = (await db.execute(select(ContextEvent).where(ContextEvent.job_run_id == run.id))).scalar_one()
            checkin = (await db.execute(select(LifeCheckin).where(LifeCheckin.life_item_id == item_id))).scalar_one()
            item = await db.get(LifeItem, item_id)
        assert run.reply_count == 1
        assert event.event_type == "job_reply"
        assert checkin.result == "done"
        assert item.status == "done"

    asyncio.run(_assert_db())


@pytest.mark.asyncio
async def test_no_reply_scanner_sends_once(monkeypatch):
    send_message = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.context_events.send_channel_message", send_message)
    job = await create_job(
        ScheduledJobCreate(
            name="Needs answer",
            agent_name="sandbox",
            schedule_type="cron",
            cron_expression="30 7 * * mon-fri",
            notification_mode="channel",
            target_channel="planning",
            expect_reply=True,
            follow_up_after_minutes=1,
        )
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await record_job_run(
        job_id=job.id,
        started_at=now - timedelta(minutes=5),
        finished_at=now - timedelta(minutes=5),
        status="delivered",
        message="ok",
        error=None,
        last_run_at=now - timedelta(minutes=5),
        next_run_at=None,
        notification_channel="planning",
        notification_channel_id="123",
        notification_message_id="777",
        awaiting_reply_until=now - timedelta(minutes=1),
    )

    result = await run_no_reply_followups(now=now)
    again = await run_no_reply_followups(now=now + timedelta(minutes=15))

    assert result == {"sent": 1, "checked": 1}
    assert again == {"sent": 0, "checked": 0}
    send_message.assert_awaited_once()
    async with async_session() as db:
        run = (await db.execute(select(JobRunLog).where(JobRunLog.notification_message_id == "777"))).scalar_one()
        events = list((await db.execute(select(ContextEvent).where(ContextEvent.job_run_id == run.id))).scalars().all())
    assert run.no_reply_follow_up_sent_at is not None
    assert any(event.event_type == "job_no_reply_followup" for event in events)
