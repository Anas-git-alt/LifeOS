from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


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
