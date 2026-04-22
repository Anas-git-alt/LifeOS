from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.config import settings
from app.database import async_session
from app.models import AuditLog, IntakeEntry, LifeCheckin, LifeItem
from app.services.intake import upsert_fallback_intake_entry
from app.services.life import _focus_rank_details


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


async def _insert_intake_entry(
    *,
    session_id: int,
    status: str,
    raw_text: str,
    follow_up_questions: list[str] | None = None,
    source_agent: str = "commitment-capture",
):
    async with async_session() as db:
        entry = IntakeEntry(
            source="agent_capture",
            source_agent=source_agent,
            source_session_id=session_id,
            raw_text=raw_text,
            title=raw_text,
            summary=raw_text,
            domain="work",
            kind="commitment",
            status=status,
            desired_outcome="Close the loop",
            next_action="Take the first step",
            follow_up_questions_json=follow_up_questions or [],
            promotion_payload_json={
                "title": raw_text,
                "kind": "task",
                "domain": "work",
                "priority": "high",
            },
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry


def test_commitment_capture_ready_auto_promotes_and_creates_follow_up(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
        assert agent_name == "commitment-capture"
        await _insert_intake_entry(session_id=session_id or 1, status="ready", raw_text=user_message)
        return {
            "response": "Ready to promote",
            "session_id": session_id,
            "session_title": "Commitment",
        }

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/commitments/capture",
            headers=_headers(),
            json={
                "message": "Send invoice",
                "new_session": True,
                "source": "test",
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
                "target_channel": "planning",
                "target_channel_id": "123",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_promoted"] is True
    assert payload["needs_follow_up"] is False
    assert payload["life_item"]["title"] == "Send invoice"
    assert payload["life_item"]["follow_up_job_id"] is not None
    assert payload["follow_up_job"]["agent_name"] == "commitment-coach"


def test_commitment_capture_clarifying_stays_in_inbox(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
        assert agent_name == "commitment-capture"
        await _insert_intake_entry(
            session_id=session_id or 1,
            status="clarifying",
            raw_text=user_message,
            follow_up_questions=["When exactly will you do it?"],
        )
        return {
            "response": "Need one more detail",
            "session_id": session_id,
            "session_title": "Commitment",
        }

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/commitments/capture",
            headers=_headers(),
            json={"message": "Send invoice", "new_session": True, "source": "test"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_promoted"] is False
    assert payload["needs_follow_up"] is True
    assert payload["life_item"] is None
    assert payload["entry"]["status"] == "clarifying"


def test_commitment_capture_deadlined_clarifying_entry_auto_promotes(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
        assert agent_name == "commitment-capture"
        await _insert_intake_entry(
            session_id=session_id or 1,
            status="clarifying",
            raw_text=user_message,
            follow_up_questions=["Who is the invoice for?"],
        )
        return {
            "response": "Need one more detail",
            "session_id": session_id,
            "session_title": "Commitment",
        }

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/commitments/capture",
            headers=_headers(),
            json={
                "message": "Send invoice",
                "new_session": True,
                "source": "test",
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_promoted"] is True
    assert payload["needs_follow_up"] is False
    assert payload["life_item"]["title"] == "Send invoice"


def test_commitment_capture_deadlined_fallback_entry_auto_promotes(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
        assert user_message == "create a one pager tomorrow at 10pm"
        await _insert_intake_entry(
            session_id=session_id or 1,
            status="clarifying",
            raw_text="create a one pager tomorrow at 10pm",
            follow_up_questions=["What is the specific deliverable?"],
        )
        async with async_session() as db:
            result = await db.execute(select(IntakeEntry).where(IntakeEntry.source_session_id == (session_id or 1)))
            entry = result.scalar_one()
            entry.domain = "planning"
            entry.kind = "idea"
            entry.promotion_payload_json = None
            await db.commit()
        return {
            "response": "Need one more detail",
            "session_id": session_id,
            "session_title": "Commitment",
        }

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/commitments/capture",
            headers=_headers(),
            json={
                "message": "create a one pager",
                "raw_message": "create a one pager tomorrow at 10pm",
                "new_session": True,
                "source": "test",
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_promoted"] is True
    assert payload["needs_follow_up"] is False
    assert payload["life_item"]["title"] == "create a one pager"
    assert payload["entry"]["status"] == "processed"


def test_commitment_capture_ready_text_without_json_auto_promotes(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
        response_text = (
            "Commitment: Build the Canva file.\n"
            "Timing is explicit; action is clear and ready to track.\n"
            "Ready to track."
        )
        await upsert_fallback_intake_entry(
            user_message=user_message,
            response_text=response_text,
            agent_name=agent_name,
            session_id=session_id,
        )
        return {
            "response": response_text,
            "session_id": session_id,
            "session_title": "Commitment",
        }

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/commitments/capture",
            headers=_headers(),
            json={
                "message": "build the canva file",
                "raw_message": "build the canva file",
                "session_id": 414,
                "new_session": False,
                "source": "test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_promoted"] is True
    assert payload["needs_follow_up"] is False
    assert payload["entry"]["status"] == "processed"
    assert payload["life_item"]["title"] == "Build the Canva file"
    assert payload["life_item"]["domain"] == "work"


def test_commitment_followup_reuses_processed_linked_entry(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _seed_processed_entry():
        async with async_session() as db:
            item = LifeItem(
                domain="work",
                kind="task",
                title="Create mockup",
                priority="medium",
                status="open",
            )
            db.add(item)
            await db.flush()
            entry = IntakeEntry(
                source="agent_capture",
                source_agent="commitment-capture",
                source_session_id=14,
                raw_text="create a one pager",
                title="Create mockup",
                summary="Create mockup",
                domain="work",
                kind="commitment",
                status="processed",
                linked_life_item_id=item.id,
                promotion_payload_json={
                    "title": "Create mockup",
                    "kind": "task",
                    "domain": "work",
                    "priority": "medium",
                },
            )
            db.add(entry)
            await db.commit()
            return entry.id, item.id

    async def _count_session_entries():
        async with async_session() as db:
            result = await db.execute(select(IntakeEntry).where(IntakeEntry.source_session_id == 14))
            return len(list(result.scalars().all()))

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
        assert session_id == 14
        return {
            "response": (
                "Ready to track\n\n"
                "[INTAKE_JSON]\n"
                '{"title":"Create mockup","kind":"commitment","domain":"work","status":"ready","summary":"Create mockup","desired_outcome":"Mockup done","next_action":"Open design tool","follow_up_questions":[],"life_item":{"title":"Create mockup","kind":"task","domain":"work","priority":"medium"}}\n'
                "[/INTAKE_JSON]"
            ),
            "session_id": session_id,
            "session_title": "Commitment",
        }

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)

    with TestClient(app) as client:
        import asyncio

        entry_id, item_id = asyncio.run(_seed_processed_entry())
        response = client.post(
            "/api/life/commitments/capture",
            headers=_headers(),
            json={
                "message": "make the mockup today",
                "raw_message": "make the mockup today",
                "session_id": 14,
                "new_session": False,
                "source": "test",
            },
        )
        entry_count = asyncio.run(_count_session_entries())

    assert response.status_code == 200
    payload = response.json()
    assert payload["entry"]["id"] == entry_id
    assert payload["life_item"]["id"] == item_id
    assert entry_count == 1


def test_commitment_followup_fallback_reuses_processed_linked_entry(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _seed_processed_entry():
        async with async_session() as db:
            item = LifeItem(
                domain="work",
                kind="task",
                title="Create mockup",
                priority="medium",
                status="open",
            )
            db.add(item)
            await db.flush()
            entry = IntakeEntry(
                source="agent_capture",
                source_agent="commitment-capture",
                source_session_id=515,
                raw_text="create a one pager",
                title="Create mockup",
                summary="Create mockup",
                domain="work",
                kind="commitment",
                status="processed",
                linked_life_item_id=item.id,
            )
            db.add(entry)
            await db.commit()
            return entry.id, item.id

    async def _count_session_entries():
        async with async_session() as db:
            result = await db.execute(select(IntakeEntry).where(IntakeEntry.source_session_id == 515))
            return len(list(result.scalars().all()))

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
        response_text = "Commitment: Create the mockup today.\nReady to track."
        await upsert_fallback_intake_entry(
            user_message=user_message,
            response_text=response_text,
            agent_name=agent_name,
            session_id=session_id,
        )
        return {
            "response": response_text,
            "session_id": session_id,
            "session_title": "Commitment",
        }

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)

    with TestClient(app) as client:
        import asyncio

        entry_id, item_id = asyncio.run(_seed_processed_entry())
        response = client.post(
            "/api/life/commitments/capture",
            headers=_headers(),
            json={
                "message": "make the mockup today",
                "raw_message": "make the mockup today",
                "session_id": 515,
                "new_session": False,
                "source": "test",
            },
        )
        entry_count = asyncio.run(_count_session_entries())

    assert response.status_code == 200
    payload = response.json()
    assert payload["entry"]["id"] == entry_id
    assert payload["entry"]["status"] == "processed"
    assert payload["life_item"]["id"] == item_id
    assert entry_count == 1


def test_snooze_item_updates_due_at_and_returns_linked_job(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    with TestClient(app) as client:
        created = client.post(
            "/api/life/items",
            headers=_headers(),
            json={"domain": "work", "title": "Send invoice", "kind": "task", "priority": "high"},
        )
        assert created.status_code == 200
        item_id = created.json()["id"]

        snoozed = client.post(
            f"/api/life/items/{item_id}/snooze",
            headers=_headers(),
            json={
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
                "timezone": "Africa/Casablanca",
                "source": "test",
            },
        )

    assert snoozed.status_code == 200
    payload = snoozed.json()
    assert payload["status"] == "open"
    assert payload["follow_up_job_id"] is not None
    assert payload["due_at"] is not None


def test_focus_rank_due_soon_beats_later_follow_up():
    tz = ZoneInfo("Africa/Casablanca")
    now_local = datetime(2026, 4, 22, 12, 15, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    due_soon_at = (now_utc + timedelta(minutes=45)).replace(tzinfo=None)
    later_due_at = (now_utc + timedelta(hours=5)).replace(tzinfo=None)
    later_follow_up_at = (now_utc + timedelta(hours=3)).replace(tzinfo=None)
    updated_at = (now_utc - timedelta(hours=1)).replace(tzinfo=None)

    due_soon = LifeItem(
        id=501,
        domain="family",
        kind="task",
        title="Send a message to your wife",
        priority="high",
        status="open",
        due_at=due_soon_at,
        updated_at=updated_at,
    )
    later_follow_up = LifeItem(
        id=502,
        domain="work",
        kind="task",
        title="Request papers from HR",
        priority="high",
        status="open",
        due_at=later_due_at,
        updated_at=updated_at,
    )

    due_soon_rank = _focus_rank_details(
        due_soon,
        tz=tz,
        today_date=now_local.date(),
        now_local=now_local,
        follow_up_due_at=None,
    )
    later_rank = _focus_rank_details(
        later_follow_up,
        tz=tz,
        today_date=now_local.date(),
        now_local=now_local,
        follow_up_due_at=later_follow_up_at,
    )

    assert due_soon_rank["sort_key"] < later_rank["sort_key"]
    assert due_soon_rank["focus_reason"].startswith("Due soon")


def test_daily_focus_coach_falls_back_to_ranked_item(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    with TestClient(app) as client:
        created = client.post(
            "/api/life/items",
            headers=_headers(),
            json={
                "domain": "work",
                "title": "Send invoice",
                "kind": "task",
                "priority": "high",
                "due_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            },
        )
        assert created.status_code == 200

        response = client.get("/api/life/coach/daily-focus", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["primary_item_id"] == created.json()["id"]


def test_weekly_commitment_review_fallback_aggregates_activity(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _seed_commitment_activity():
        async with async_session() as db:
            item = LifeItem(
                domain="work",
                kind="task",
                title="Send invoice",
                priority="high",
                status="open",
                follow_up_job_id=91,
                due_at=(datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None),
                updated_at=(datetime.now(timezone.utc) - timedelta(days=8)).replace(tzinfo=None),
            )
            db.add(item)
            await db.flush()
            db.add(
                LifeCheckin(
                    life_item_id=item.id,
                    result="done",
                    note="closed",
                    timestamp=(datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None),
                )
            )
            db.add(
                AuditLog(
                    agent_name="commitment-loop",
                    action="life_item_snoozed",
                    details=f"item_id={item.id}",
                    status="completed",
                )
            )
            await db.commit()

    with TestClient(app) as client:
        import asyncio

        asyncio.run(_seed_commitment_activity())
        response = client.get("/api/life/coach/weekly-review", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["wins"]
    assert payload["repeat_blockers"]


def test_weekly_commitment_review_does_not_mark_fresh_due_items_stale(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _seed_fresh_due_commitment():
        async with async_session() as db:
            item = LifeItem(
                domain="family",
                kind="task",
                title="Fresh due commitment",
                priority="high",
                status="open",
                follow_up_job_id=93,
                due_at=(datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(item)
            await db.commit()

    with TestClient(app) as client:
        import asyncio

        asyncio.run(_seed_fresh_due_commitment())
        response = client.get("/api/life/coach/weekly-review", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert "Fresh due commitment" not in payload["stale_commitments"]


def test_weekly_commitment_review_handles_old_naive_updated_at(monkeypatch):
    monkeypatch.setattr("app.services.life.get_today_schedule", AsyncMock(return_value={"next_prayer": None, "windows": []}))

    async def _seed_stale_commitment():
        async with async_session() as db:
            item = LifeItem(
                domain="work",
                kind="task",
                title="Draft presentation",
                priority="high",
                status="open",
                follow_up_job_id=92,
                due_at=None,
                updated_at=(datetime.now(timezone.utc) - timedelta(days=8)).replace(tzinfo=None),
            )
            db.add(item)
            await db.commit()

    with TestClient(app) as client:
        import asyncio

        asyncio.run(_seed_stale_commitment())
        response = client.get("/api/life/coach/weekly-review", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["wins"] or payload["stale_commitments"]
