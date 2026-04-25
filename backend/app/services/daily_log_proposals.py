"""Propose daily-log mutations from flexible check-in text."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models import Agent, DailyLogCreate
from app.services.provider_router import LLMProvidersExhaustedError, chat_completion

CHECKIN_SIGNAL_RE = re.compile(
    r"\b("
    r"i|we|just|done|completed|finished|drank|drink|ate|eat|had|meal|water|cup|glass|"
    r"shawarma|sandwich|sandwitch|trained|worked out|rested|sent|called|texted|messaged"
    r")\b",
    re.IGNORECASE,
)
COMPLETED_CHECKIN_RE = re.compile(
    r"\b(i|we|just)\s+(drank|ate|had|trained|worked out|rested|sent|called|texted|messaged|finished|completed|did)\b|"
    r"\b(done|completed|finished)\b",
    re.IGNORECASE,
)
PLANNING_OR_QUESTION_RE = re.compile(r"\?|(\b(should|need to|plan to|want to|tomorrow|later|remind me)\b)", re.IGNORECASE)
WATER_RE = re.compile(r"\b(water|hydration|drank|drink|cup|cups|glass|glasses|bottle|bottles)\b", re.IGNORECASE)
WATER_COUNT_RE = re.compile(r"\b(\d+)\s*(?:cup|cups|glass|glasses|bottle|bottles)\b", re.IGNORECASE)
MEAL_RE = re.compile(
    r"\b(ate|eat|meal|breakfast|lunch|dinner|shawarma|sandwich|sandwitch|food|protein)\b",
    re.IGNORECASE,
)
TRAINING_RE = re.compile(r"\b(trained|workout|worked out|gym|walk|stretch|stretching)\b", re.IGNORECASE)
REST_RE = re.compile(r"\b(rested|rest day|explicit rest)\b", re.IGNORECASE)
FAMILY_RE = re.compile(r"\b(sent|called|texted|messaged|spoke)\b.*\b(mother|mom|father|dad|wife|family|parents)\b", re.IGNORECASE)
PRIORITY_RE = re.compile(r"\b(finished|completed|shipped|done)\b.*\b(priority|invoice|task|commitment)\b", re.IGNORECASE)
NEGATED_WATER_RE = re.compile(r"\b(no|not|didn'?t|did not|haven'?t|have not)\b.{0,24}\b(water|drink|drank|hydration)\b", re.IGNORECASE)
NEGATED_MEAL_RE = re.compile(r"\b(no|not|didn'?t|did not|haven'?t|have not)\b.{0,24}\b(ate|eat|meal|food)\b", re.IGNORECASE)


def _water_count(text: str) -> int:
    match = WATER_COUNT_RE.search(text)
    if not match:
        return 1
    return max(1, min(12, int(match.group(1))))


def _normalise_logs(raw_logs: Any, *, note: str) -> list[dict[str, Any]]:
    if not isinstance(raw_logs, list):
        return []
    logs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_logs:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in {"sleep", "meal", "training", "hydration", "shutdown", "family", "priority"}:
            continue
        key = kind
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, Any] = {"kind": kind, "note": str(item.get("note") or note)[:500]}
        if kind in {"meal", "hydration", "priority"}:
            try:
                payload["count"] = max(1, min(12, int(item.get("count") or 1)))
            except (TypeError, ValueError):
                payload["count"] = 1
        if kind in {"family", "shutdown"}:
            payload["done"] = bool(item.get("done", True))
        if kind == "training":
            status = str(item.get("status") or "done").strip().lower()
            payload["status"] = status if status in {"done", "rest", "missed"} else "done"
        if kind == "meal" and item.get("protein_hit") is not None:
            payload["protein_hit"] = bool(item.get("protein_hit"))
        try:
            DailyLogCreate(**payload)
        except Exception:
            continue
        logs.append(payload)
    return logs


def _fallback_logs(text: str) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    note = text.strip()[:500]
    if WATER_RE.search(text) and not NEGATED_WATER_RE.search(text):
        logs.append({"kind": "hydration", "count": _water_count(text), "note": note})
    if MEAL_RE.search(text) and not NEGATED_MEAL_RE.search(text):
        logs.append({"kind": "meal", "count": 1, "note": note, "protein_hit": "protein" in text.lower()})
    if TRAINING_RE.search(text):
        logs.append({"kind": "training", "status": "done", "note": note})
    elif REST_RE.search(text):
        logs.append({"kind": "training", "status": "rest", "note": note})
    if FAMILY_RE.search(text):
        logs.append({"kind": "family", "done": True, "note": note})
    if PRIORITY_RE.search(text):
        logs.append({"kind": "priority", "count": 1, "note": note})
    return _normalise_logs(logs, note=note)


async def propose_daily_log_payload(text: str, *, agent: Agent | None = None) -> dict[str, Any] | None:
    message = str(text or "").strip()
    if not message or not CHECKIN_SIGNAL_RE.search(message):
        return None
    if PLANNING_OR_QUESTION_RE.search(message) and not COMPLETED_CHECKIN_RE.search(message):
        return None

    logs: list[dict[str, Any]] = []
    if agent:
        system = (
            "Extract LifeOS daily quick logs from the user's check-in. "
            "Return only JSON: {\"logs\":[...]} with allowed kinds: meal, hydration, training, family, priority, shutdown, sleep. "
            "Use count for meal/hydration/priority, done for family/shutdown, status done/rest/missed for training. "
            "If the user is asking for advice, planning future actions, or negating an action, return {\"logs\":[]}."
        )
        try:
            raw = await chat_completion(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
                provider=agent.provider,
                model=agent.model,
                fallback_provider=agent.fallback_provider,
                fallback_model=agent.fallback_model,
                temperature=0.0,
                max_tokens=300,
            )
            start = raw.find("{")
            end = raw.rfind("}")
            parsed = json.loads(raw[start : end + 1]) if start >= 0 and end >= start else {}
            logs = _normalise_logs(parsed.get("logs"), note=message)
        except (LLMProvidersExhaustedError, json.JSONDecodeError, ValueError, TypeError):
            logs = []
        except Exception:
            logs = []

    if not logs:
        logs = _fallback_logs(message)
    if not logs:
        return None
    return {"logs": logs, "source_text": message}


def format_daily_log_proposal(payload: dict[str, Any]) -> str:
    labels = []
    for item in payload.get("logs") or []:
        kind = item.get("kind")
        if kind in {"hydration", "meal", "priority"}:
            labels.append(f"{kind} x{item.get('count', 1)}")
        elif kind == "training":
            labels.append(f"training:{item.get('status', 'done')}")
        elif kind in {"family", "shutdown"}:
            labels.append(kind)
        else:
            labels.append(str(kind))
    return ", ".join(labels)
