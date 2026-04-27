from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.main import app
from app.models import Agent, IntakeEntry, SharedMemoryProposal
from app.services.life_synthesis import _augment_item_from_raw, _score_item
from app.services.vault import classify_note_path


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


def _default_payload() -> dict:
    return {
        "items": [
            {
                "title": "Ship client invoice",
                "kind": "task",
                "domain": "work",
                "status": "ready",
                "summary": "Invoice must be sent today.",
                "desired_outcome": "Client invoice sent.",
                "next_action": "Open invoice draft and send it.",
                "follow_up_questions": [],
                "priority": "high",
                "priority_score": 82,
                "priority_reason": "Deadline and payment loop affect work commitments.",
            },
            {
                "title": "Improve sleep routine",
                "kind": "habit",
                "domain": "health",
                "status": "clarifying",
                "summary": "Sleep routine needs a concrete target.",
                "desired_outcome": "Stable bedtime.",
                "next_action": "Pick realistic bedtime.",
                "follow_up_questions": ["What bedtime is realistic?"],
                "priority": "medium",
            },
        ],
        "wiki_facts": [
            {
                "title": "Invoice follow-through matters",
                "domain": "work",
                "content": "User wants invoice follow-through treated as high leverage because it closes payment loops.",
                "confidence": "medium",
            }
        ],
    }


def test_synthesis_coerces_event_logistics_out_of_health_domain():
    item = _augment_item_from_raw(
        {"title": "Pick up suit from ironing shop", "kind": "task", "domain": "health", "priority": "high"},
        "Wedding next Sunday; take suit to ironing shop Thursday and pick it up Saturday morning.",
    )

    assert item["domain"] == "planning"

    score, factors, reason = _score_item(item, context_links=[], now_utc=datetime(2026, 4, 26, tzinfo=timezone.utc))

    assert "life_anchor:health" not in factors["signals"]
    assert "health" not in reason.lower()
    assert score >= 0


async def _insert_synthesis_entry(*, session_id: int, raw_text: str, payload: dict | None = None):
    payload = payload or _default_payload()
    async with async_session() as db:
        agent = await db.scalar(select(Agent).where(Agent.name == "intake-inbox"))
        if agent is None:
            db.add(
                Agent(
                    name="intake-inbox",
                    description="Test intake agent",
                    system_prompt="Capture raw life input.",
                    memory_scopes_json=["shared_global", "shared_domain"],
                    shared_domains_json=["work", "health", "planning"],
                )
            )
        entry = IntakeEntry(
            source="agent_capture",
            source_agent="intake-inbox",
            source_session_id=session_id,
            raw_text=raw_text,
            title="Raw life dump",
            summary="Raw life dump",
            domain="planning",
            kind="idea",
            status="ready",
            structured_data_json=payload,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry


def test_inbox_capture_synthesizes_priorities_and_auto_creates_items(monkeypatch):
    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool, **_extra):
        assert agent_name == "intake-inbox"
        await _insert_synthesis_entry(session_id=session_id or 1, raw_text=user_message)
        return {
            "response": "Captured and ranked.",
            "session_id": session_id,
            "session_title": "Raw life dump",
        }

    async def _fake_search_shared_memory(**_kwargs):
        return [
            SimpleNamespace(
                title="Work operating principle",
                uri="viking://resources/lifeos/obsidian/shared/domains/work/invoice.md",
                path="/vault/shared/domains/work/invoice.md",
                domain="work",
                source="exact",
                score=1.0,
            )
        ]

    async def _fake_create_proposal(payload):
        return SimpleNamespace(
            id=44,
            source_agent=payload.agent_name,
            source_session_id=payload.session_id,
            scope=payload.scope,
            domain=payload.domain,
            title=payload.title,
            target_path="/vault/shared/domains/work/invoice-follow-through.md",
            proposal_path="/vault/inbox/proposals/invoice-follow-through.md",
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

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)
    monkeypatch.setattr("app.services.life_synthesis.search_shared_memory", _fake_search_shared_memory)
    monkeypatch.setattr("app.services.life_synthesis.create_shared_memory_review_proposal", _fake_create_proposal)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/inbox/capture",
            headers=_headers(),
            json={"message": "Need invoice sent today and sleep routine fixed", "new_session": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_promoted_count"] == 1
    assert len(payload["entries"]) == 2
    assert len(payload["life_items"]) == 1
    assert payload["life_items"][0]["title"] == "Ship client invoice"
    assert payload["life_items"][0]["priority"] == "high"
    assert payload["life_items"][0]["priority_score"] >= 82
    assert "Deadline" in payload["life_items"][0]["priority_reason"]
    assert payload["life_items"][0]["context_links"][0]["title"] == "Work operating principle"
    assert payload["entries"][1]["status"] == "clarifying"
    assert payload["wiki_proposals"][0]["title"] == "Invoice follow-through matters"


def test_inbox_capture_infers_due_time_from_raw_message(monkeypatch):
    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool, **_extra):
        await _insert_synthesis_entry(session_id=session_id or 1, raw_text=user_message)
        return {"response": "Captured.", "session_id": session_id, "session_title": "Raw life dump"}

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)
    monkeypatch.setattr("app.services.life_synthesis.search_shared_memory", lambda **_kwargs: [])
    monkeypatch.setattr("app.services.life_synthesis.create_shared_memory_review_proposal", lambda *_args, **_kwargs: None)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/inbox/capture",
            headers=_headers(),
            json={"message": "Need invoice sent today before 5pm and sleep routine fixed", "new_session": True},
        )

    assert response.status_code == 200
    life_item = response.json()["life_items"][0]
    assert life_item["due_at"] is not None
    assert life_item["priority_score"] >= 90


def test_inbox_capture_does_not_apply_invoice_deadline_to_all_split_items(monkeypatch):
    payload_with_mixed_kinds = {
        "items": [
            {
                "title": "Send client invoice today before 5pm",
                "kind": "habit",
                "domain": "work",
                "status": "ready",
                "summary": "Client invoice due today.",
                "next_action": "Send invoice today.",
                "follow_up_questions": [],
                "priority": "high",
                "priority_score": 90,
                "priority_reason": "High leverage.",
            },
            {
                "title": "Establish sleep routine",
                "kind": "habit",
                "domain": "health",
                "status": "clarifying",
                "summary": "Sleep target: 23:30.",
                "next_action": "Set bedtime routine.",
                "follow_up_questions": [],
                "priority": "medium",
                "priority_score": 60,
            },
            {
                "title": "Family call tomorrow after Asr",
                "kind": "habit",
                "domain": "family",
                "status": "ready",
                "summary": "Family call tomorrow.",
                "next_action": "Prepare for call.",
                "follow_up_questions": [],
                "priority": "low",
                "priority_score": 40,
            },
        ],
        "wiki_facts": [],
    }

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool, **_extra):
        await _insert_synthesis_entry(session_id=session_id or 1, raw_text=user_message, payload=payload_with_mixed_kinds)
        return {"response": "Captured.", "session_id": session_id, "session_title": "Raw life dump"}

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)
    monkeypatch.setattr("app.services.life_synthesis.search_shared_memory", lambda **_kwargs: [])

    with TestClient(app) as client:
        response = client.post(
            "/api/life/inbox/capture",
            headers=_headers(),
            json={
                "message": (
                    "send client invoice today before 5pm, sleep target bed 23:30 wake 07:10, "
                    "family call tomorrow after Asr"
                ),
                "new_session": True,
                "source_message_id": "discord-123",
                "source_channel_id": "channel-456",
            },
        )

    assert response.status_code == 200
    by_title = {item["title"]: item for item in response.json()["life_items"]}
    assert by_title["Send client invoice today before 5pm"]["kind"] == "task"
    assert by_title["Send client invoice today before 5pm"]["due_at"] is not None
    assert by_title["Establish sleep routine"]["kind"] == "habit"
    assert by_title["Establish sleep routine"]["due_at"] is None
    assert by_title["Establish sleep routine"]["priority"] == "high"
    assert by_title["Family call tomorrow after Asr"]["kind"] == "task"
    assert by_title["Family call tomorrow after Asr"]["due_at"] is None
    assert by_title["Family call tomorrow after Asr"]["priority"] == "medium"


def test_inbox_capture_semantic_guard_blocks_unrelated_item(monkeypatch):
    mismatched_payload = {
        "items": [
            {
                "title": "Fix bedtime routine",
                "kind": "habit",
                "domain": "health",
                "status": "ready",
                "summary": "Bedtime routine needs work.",
                "follow_up_questions": [],
                "priority": "high",
                "priority_score": 90,
            }
        ],
        "wiki_facts": [],
    }

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool, **_extra):
        await _insert_synthesis_entry(session_id=session_id or 1, raw_text=user_message, payload=mismatched_payload)
        return {"response": "Captured.", "session_id": session_id, "session_title": "Wedding logistics"}

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)
    monkeypatch.setattr("app.services.life_synthesis.search_shared_memory", lambda **_kwargs: [])

    with TestClient(app) as client:
        response = client.post(
            "/api/life/inbox/capture",
            headers=_headers(),
            json={
                "message": (
                    "I have a wedding next Sunday 3rd May, need to take my suit to the ironing shop "
                    "Thursday and pick it up Saturday morning"
                ),
                "new_session": True,
                "source_message_id": "discord-123",
                "source_channel_id": "channel-456",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["life_items"] == []
    assert payload["entries"][0]["status"] == "clarifying"
    assert "Fix bedtime" not in payload["entries"][0]["title"]
    assert payload["entries"][0]["follow_up_questions"]
    assert payload["entries"][0]["structured_data"]["raw_user_input"].startswith("I have a wedding")
    assert payload["entries"][0]["structured_data"]["capture_source"]["source_message_id"] == "discord-123"


def test_inbox_capture_uses_raw_followup_to_rescue_sleep_and_family(monkeypatch):
    followup_payload = {
        "items": [
            {
                "title": "Fix sleep routine",
                "kind": "habit",
                "domain": "health",
                "status": "clarifying",
                "summary": "Sleep routine needs a concrete target.",
                "follow_up_questions": ["What bedtime and wake time?"],
                "priority": "medium",
            }
        ],
        "wiki_facts": [],
    }

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool, **_extra):
        await _insert_synthesis_entry(session_id=session_id or 1, raw_text=user_message, payload=followup_payload)
        return {"response": "Captured.", "session_id": session_id, "session_title": "Follow-up"}

    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)
    monkeypatch.setattr("app.services.life_synthesis.search_shared_memory", lambda **_kwargs: [])

    with TestClient(app) as client:
        response = client.post(
            "/api/life/inbox/capture",
            headers=_headers(),
            json={"message": "sleep target is bed 23:30 wake 07:10, family call is tomorrow after Asr", "new_session": True},
        )

    assert response.status_code == 200
    payload = response.json()
    titles = {item["title"] for item in payload["life_items"]}
    assert payload["auto_promoted_count"] == 2
    assert "Fix sleep routine" in titles
    assert "Call family tomorrow after Asr" in titles


def test_inbox_capture_skips_duplicate_pending_wiki_proposal(monkeypatch):
    title = "Sleep routine priority"
    target_path = classify_note_path(scope="shared_domain", domain="health", agent_name="wiki-curator", title=title)
    duplicate_payload = {
        "items": [
            {
                "title": "Review sleep routine",
                "kind": "habit",
                "domain": "health",
                "status": "clarifying",
                "follow_up_questions": ["What target?"],
            }
        ],
        "wiki_facts": [
            {
                "title": title,
                "domain": "health",
                "content": "User treats sleep routine as a core priority.",
            }
        ],
    }

    async def _seed_duplicate():
        async with async_session() as db:
            db.add(
                SharedMemoryProposal(
                    source_agent="wiki-curator",
                    scope="shared_domain",
                    domain="health",
                    title=title,
                    target_path=str(target_path),
                    proposal_path="/tmp/proposal.md",
                    conflict_reason="review_required",
                    status="pending",
                    proposed_content="existing",
                    note_metadata_json={},
                )
            )
            await db.commit()

    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool, **_extra):
        await _insert_synthesis_entry(session_id=session_id or 1, raw_text=user_message, payload=duplicate_payload)
        return {"response": "Captured.", "session_id": session_id, "session_title": "Duplicate"}

    async def _should_not_create(*_args, **_kwargs):
        raise AssertionError("duplicate wiki proposal should be skipped")

    import anyio

    anyio.run(_seed_duplicate)
    monkeypatch.setattr("app.routers.life.handle_message", _fake_handle_message)
    monkeypatch.setattr("app.services.life_synthesis.create_shared_memory_review_proposal", _should_not_create)

    with TestClient(app) as client:
        response = client.post(
            "/api/life/inbox/capture",
            headers=_headers(),
            json={"message": "sleep routine target still matters", "new_session": True},
        )

    assert response.status_code == 200
    assert response.json()["wiki_proposals"] == []
