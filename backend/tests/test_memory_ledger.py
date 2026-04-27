from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.memory_ledger import record_capture_memory, record_memory_event, render_memory_ledger_context, search_memory_events


@pytest.mark.asyncio
async def test_memory_ledger_search_returns_exact_prior_capture_details():
    await record_memory_event(
        raw_text=(
            "HR tax return papers needed:\n"
            "Attestation de salaire annuel (36 mois)\n"
            "Attestation de salaire mensuel\n"
            "Attestation de travail\n"
            "Copie du contrat de travail\n"
            "Attestation de declaration de salaire a la CNSS"
        ),
        source="test",
        source_agent="commitment-capture",
        source_session_id=14,
        event_type="commitment_capture",
        domain="work",
        kind="commitment",
        title="Request HR for tax return documents",
    )

    hits = await search_memory_events(
        query="what papers did I say I need from HR for tax return",
        agent=SimpleNamespace(name="sandbox", shared_domains=[]),
    )

    assert hits
    assert "Attestation de salaire mensuel" in hits[0].raw_text
    assert "CNSS" in hits[0].raw_text
    context = render_memory_ledger_context(hits)
    assert "[PRIVATE MEMORY LEDGER]" in context
    assert "Copie du contrat de travail" in context


@pytest.mark.asyncio
async def test_capture_memory_includes_linked_life_item_deadline():
    await record_capture_memory(
        raw_text="Request HR papers. Follow-up answer: deadline is at 2pm tomorrow",
        source="test",
        source_agent="commitment-capture",
        source_session_id=15,
        event_type="commitment_capture",
        life_item=SimpleNamespace(
            id=51,
            title="Request HR papers",
            domain="work",
            kind="task",
            due_at=datetime(2026, 4, 28, 13, 0),
        ),
    )

    hits = await search_memory_events(
        query="when request HR papers deadline",
        agent=SimpleNamespace(name="sandbox", shared_domains=[]),
    )

    assert hits
    assert "Tracked deadline UTC: 2026-04-28T13:00:00+00:00" in render_memory_ledger_context(hits)
