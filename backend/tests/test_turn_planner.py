from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.turn_planner import plan_turn_for_tools


@pytest.mark.asyncio
async def test_turn_planner_infers_weather_search_from_short_location_followup(monkeypatch):
    agent = SimpleNamespace(
        provider="test",
        model="test",
        fallback_provider=None,
        fallback_model=None,
    )
    monkeypatch.setattr(
        "app.services.turn_planner.chat_completion",
        AsyncMock(
            return_value='{"needs_web_search": true, "web_search_query": "current weather Casablanca Morocco", "confidence": 0.93}'
        ),
    )

    plan = await plan_turn_for_tools(
        agent=agent,
        user_message="casablanca",
        context=[{"role": "user", "content": "how is the wether today?"}],
        current_datetime="Sunday, April 26, 2026 at 08:45 UTC",
    )

    assert plan.needs_web_search is True
    assert plan.web_search_query == "current weather Casablanca Morocco"
    assert plan.confidence == 0.93
