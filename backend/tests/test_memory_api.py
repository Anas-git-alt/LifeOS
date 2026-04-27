from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import anyio

from app.config import settings
from app.main import app
from app.services.memory_ledger import record_memory_event, search_memory_events


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


def test_memory_api_promote_search_and_conflicts(monkeypatch):
    monkeypatch.setattr(
        "app.services.shared_memory.openviking_client.search",
        AsyncMock(return_value=SimpleNamespace(resources=[], memories=[], skills=[])),
    )

    with TestClient(app) as client:
        create_agent = client.post(
            "/api/agents/",
            headers=_headers(),
            json={
                "name": "health-fitness",
                "description": "health",
                "system_prompt": "health",
                "workspace_enabled": False,
                "memory_scopes": ["shared_domain", "shared_global", "agent_private", "session"],
                "shared_domains": ["health"],
            },
        )
        assert create_agent.status_code == 200

        first = client.post(
            "/api/memory/promote",
            headers=_headers(),
            json={
                "agent_name": "health-fitness",
                "title": "Sleep Routine",
                "content": "First version.",
                "scope": "shared_domain",
                "domain": "health",
            },
        )
        assert first.status_code == 200
        assert first.json()["status"] == "created"

        second = client.post(
            "/api/memory/promote",
            headers=_headers(),
            json={
                "agent_name": "health-fitness",
                "title": "Sleep Routine",
                "content": "Second version.",
                "scope": "shared_domain",
                "domain": "health",
            },
        )
        assert second.status_code == 200
        assert second.json()["status"] == "conflict"
        proposal_id = second.json()["proposal_id"]

        conflicts = client.get("/api/vault/conflicts", headers=_headers())
        assert conflicts.status_code == 200
        assert len(conflicts.json()) == 1

        search = client.get(
            "/api/memory/shared/search",
            headers=_headers(),
            params={"agent_name": "health-fitness", "query": "sleep routine"},
        )
        assert search.status_code == 200
        assert any("sleep-routine.md" in hit["path"] for hit in search.json()["hits"])

        apply_resp = client.post(
            f"/api/memory/proposals/{proposal_id}/apply",
            headers=_headers(),
            json={"source_agent": "webui"},
        )
        assert apply_resp.status_code == 200
        assert apply_resp.json()["status"] == "applied"


def test_private_memory_api_lists_archives_and_restores():
    async def _seed_event():
        return await record_memory_event(
            raw_text="Remember that I prefer concise staging UAT notes.",
            source="test",
            source_agent="sandbox",
            source_session_id=9,
            event_type="user_turn",
            domain="planning",
            kind="preference",
            title="Concise staging UAT notes",
        )

    event = anyio.run(_seed_event)

    with TestClient(app) as client:
        active = client.get("/api/memory/private/events", headers=_headers(), params={"status": "active"})
        assert active.status_code == 200
        row = next(item for item in active.json() if item["id"] == event.id)
        assert row["source_message"] == "Remember that I prefer concise staging UAT notes."
        assert row["scope"] == "private"
        assert row["why_saved"]

        archived = client.post(f"/api/memory/private/events/{event.id}/archive", headers=_headers())
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"

        async def _search_hits():
            return await search_memory_events(
                query="concise staging UAT notes",
                agent=SimpleNamespace(name="sandbox", shared_domains=[]),
            )

        hits = anyio.run(_search_hits)
        assert hits == []

        restored = client.post(f"/api/memory/private/events/{event.id}/restore", headers=_headers())
        assert restored.status_code == 200
        assert restored.json()["status"] == "active"
