from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import SharedMemoryPromoteRequest
from app.services.shared_memory import (
    apply_shared_memory_proposal,
    build_shared_memory_context,
    list_shared_memory_proposals,
    promote_to_shared_memory,
    search_shared_memory,
)
from app.services.vault import obsidian_vault_root


@pytest.mark.asyncio
async def test_promote_shared_memory_creates_note_and_exact_search_finds_it(monkeypatch):
    monkeypatch.setattr("app.services.shared_memory.openviking_client.search", AsyncMock(side_effect=RuntimeError("offline")))

    result = await promote_to_shared_memory(
        SharedMemoryPromoteRequest(
            agent_name="health-fitness",
            title="Sleep Routine",
            content="Target bedtime 23:00 and reduce late caffeine.",
            scope="shared_domain",
            domain="health",
            tags=["sleep", "routine"],
        )
    )

    assert result["status"] == "created"
    assert result["target_path"].endswith("/shared/domains/health/sleep-routine.md")

    hits = await search_shared_memory(
        query="sleep routine bedtime",
        agent=SimpleNamespace(
            name="health-fitness",
            memory_scopes=["shared_domain", "shared_global", "agent_private", "session"],
            shared_domains=["health"],
        ),
    )

    assert any(hit.path.endswith("/shared/domains/health/sleep-routine.md") for hit in hits)


@pytest.mark.asyncio
async def test_promote_shared_memory_creates_conflict_proposal_when_checksum_missing(monkeypatch):
    monkeypatch.setattr("app.services.shared_memory.openviking_client.search", AsyncMock(side_effect=RuntimeError("offline")))

    await promote_to_shared_memory(
        SharedMemoryPromoteRequest(
            agent_name="health-fitness",
            title="Sleep Routine",
            content="Original note body.",
            scope="shared_domain",
            domain="health",
        )
    )

    result = await promote_to_shared_memory(
        SharedMemoryPromoteRequest(
            agent_name="health-fitness",
            title="Sleep Routine",
            content="Updated note body.",
            scope="shared_domain",
            domain="health",
        )
    )

    assert result["status"] == "conflict"
    assert result["proposal_id"] is not None
    assert result["proposal_path"]
    proposals = await list_shared_memory_proposals()
    assert len(proposals) == 1
    assert proposals[0].target_path.endswith("/shared/domains/health/sleep-routine.md")


@pytest.mark.asyncio
async def test_apply_shared_memory_proposal_updates_target(monkeypatch):
    monkeypatch.setattr("app.services.shared_memory.openviking_client.search", AsyncMock(side_effect=RuntimeError("offline")))

    created = await promote_to_shared_memory(
        SharedMemoryPromoteRequest(
            agent_name="health-fitness",
            title="Sleep Routine",
            content="First version.",
            scope="shared_domain",
            domain="health",
        )
    )
    conflict = await promote_to_shared_memory(
        SharedMemoryPromoteRequest(
            agent_name="health-fitness",
            title="Sleep Routine",
            content="Second version.",
            scope="shared_domain",
            domain="health",
        )
    )

    applied = await apply_shared_memory_proposal(int(conflict["proposal_id"]), source_agent="webui")

    assert created["target_path"] == applied["target_path"]
    target_text = (obsidian_vault_root() / "shared" / "domains" / "health" / "sleep-routine.md").read_text(
        encoding="utf-8"
    )
    assert "Second version." in target_text


@pytest.mark.asyncio
async def test_build_shared_memory_context_includes_router_hubs_and_exact_note(monkeypatch):
    monkeypatch.setattr(
        "app.services.shared_memory.openviking_client.search",
        AsyncMock(return_value=SimpleNamespace(resources=[], memories=[], skills=[])),
    )
    await promote_to_shared_memory(
        SharedMemoryPromoteRequest(
            agent_name="health-fitness",
            title="Sleep Routine",
            content="Target bedtime 23:00.",
            scope="shared_domain",
            domain="health",
        )
    )

    context = await build_shared_memory_context(
        agent=SimpleNamespace(
            name="health-fitness",
            memory_scopes=["shared_domain", "shared_global", "agent_private", "session"],
            shared_domains=["health"],
        ),
        query="what is my sleep routine target bedtime",
    )

    assert "[SHARED MEMORY ROUTER]" in context
    assert "[SHARED MEMORY HUBS]" in context
    assert "sleep-routine.md" in context
