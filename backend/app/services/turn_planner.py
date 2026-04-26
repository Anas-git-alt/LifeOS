"""Agentic preflight planner for tool selection."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.models import Agent
from app.services.provider_router import LLMProvidersExhaustedError, chat_completion


@dataclass(slots=True)
class TurnPlan:
    needs_web_search: bool = False
    web_search_query: str | None = None
    confidence: float = 0.0


def _recent_context_text(context: list[dict[str, Any]], *, limit: int = 6) -> str:
    lines: list[str] = []
    for item in context[-limit:]:
        role = str(item.get("role") or "unknown")
        content = str(item.get("content") or "").replace("\n", " ").strip()
        if content:
            lines.append(f"{role}: {content[:500]}")
    return "\n".join(lines)


def _parse_plan(raw: str) -> TurnPlan:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return TurnPlan()
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return TurnPlan()
    query = str(parsed.get("web_search_query") or "").strip()
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return TurnPlan(
        needs_web_search=bool(parsed.get("needs_web_search")) and bool(query),
        web_search_query=query or None,
        confidence=confidence,
    )


async def plan_turn_for_tools(
    *,
    agent: Agent,
    user_message: str,
    context: list[dict[str, Any]] | None = None,
    current_datetime: str,
) -> TurnPlan:
    """Ask the model which external tools this turn needs.

    This is intentionally a planner, not a final-answer call. It lets the system
    handle fragments like "casablanca" after "how is the weather today?" without
    adding a new hard-coded parser for every wording.
    """
    system = (
        "You are the LifeOS turn planner. Decide whether this turn needs web search before the final answer. "
        "Use the current message plus recent context. Return only JSON with keys: "
        "needs_web_search boolean, web_search_query string, confidence number 0-1.\n"
        "Use web search for current external facts: weather, prices, news, latest/current status, scores, releases. "
        "If the current message is a short fragment that completes the previous request, infer the full query. "
        "For example, previous user asked weather and current user says 'casablanca' -> search 'current weather Casablanca Morocco'. "
        "Do not request web search for local LifeOS tasks, memories, workspace questions, or pure planning.\n"
        f"Current date/time: {current_datetime}"
    )
    user = (
        f"Recent context:\n{_recent_context_text(context or []) or 'none'}\n\n"
        f"Current user message:\n{user_message}"
    )
    try:
        raw = await chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            provider=agent.provider,
            model=agent.model,
            fallback_provider=agent.fallback_provider,
            fallback_model=agent.fallback_model,
            temperature=0.0,
            max_tokens=180,
        )
    except (LLMProvidersExhaustedError, Exception):
        return TurnPlan()
    return _parse_plan(raw)
