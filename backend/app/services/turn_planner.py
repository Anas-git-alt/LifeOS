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


def _profile_context_text(state_packet: dict[str, Any] | None) -> str:
    if not isinstance(state_packet, dict):
        return "none"
    profile = state_packet.get("profile")
    if not isinstance(profile, dict):
        return "none"
    parts = []
    for key in ("city", "country", "timezone"):
        value = str(profile.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    return ", ".join(parts) if parts else "none"


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
    state_packet: dict[str, Any] | None = None,
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
        "Use web search for local recommendations or budget shopping only when the user asks for current local prices, availability, stores, or where to buy. "
        "Do not use web search for general recipe, meal idea, cooking-detail, or macro-estimate questions; answer from model knowledge and profile locale. "
        "Use web search for hardware/product shopping questions about cheapest, used/new market, listings, availability, or current prices. "
        "When the user asks for weather or local external info without naming a place, default to the LifeOS profile city/country. "
        "If the current message is a short fragment that completes the previous request, infer the full query. "
        "For example, previous user asked weather and current user says 'casablanca' -> search 'current weather Casablanca Morocco'. "
        "For example, profile city Casablanca and user asks 'how is weather today?' -> search 'current weather Casablanca Morocco'. "
        "For example, profile city Casablanca and user asks cheap high-protein meal idea -> no web search. "
        "For example, profile city Casablanca and user asks current tuna prices near me -> search 'current tuna prices Casablanca Morocco'. "
        "For LifeOS planning like 'what should I do today?', do not search; the final agent should use the LifeOS state packet. "
        "Do not request web search for local LifeOS tasks, memories, workspace questions, or pure planning.\n"
        f"Current date/time: {current_datetime}"
    )
    user = (
        f"LifeOS profile context:\n{_profile_context_text(state_packet)}\n\n"
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
