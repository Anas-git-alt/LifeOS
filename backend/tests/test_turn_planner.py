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


@pytest.mark.asyncio
async def test_turn_planner_includes_profile_location_for_local_queries(monkeypatch):
    agent = SimpleNamespace(
        provider="test",
        model="test",
        fallback_provider=None,
        fallback_model=None,
    )
    captured: dict[str, object] = {}

    async def fake_chat_completion(messages, **_kwargs):
        captured["messages"] = messages
        return '{"needs_web_search": true, "web_search_query": "current weather Casablanca Morocco", "confidence": 0.91}'

    monkeypatch.setattr("app.services.turn_planner.chat_completion", fake_chat_completion)

    plan = await plan_turn_for_tools(
        agent=agent,
        user_message="how is the wether today?",
        context=[],
        current_datetime="Sunday, April 26, 2026 at 08:45 UTC",
        state_packet={"profile": {"city": "Casablanca", "country": "Morocco", "timezone": "Africa/Casablanca"}},
    )

    assert plan.needs_web_search is True
    assert plan.web_search_query == "current weather Casablanca Morocco"
    prompt_text = captured["messages"][1]["content"]
    assert "city=Casablanca" in prompt_text
    assert "country=Morocco" in prompt_text
