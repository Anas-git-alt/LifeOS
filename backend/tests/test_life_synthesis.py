from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.main import app
from app.models import Agent, IntakeEntry


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


async def _insert_synthesis_entry(*, session_id: int, raw_text: str):
    payload = {
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
    async def _fake_handle_message(*, agent_name: str, user_message: str, approval_policy: str, source: str, session_id: int | None, session_enabled: bool):
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
