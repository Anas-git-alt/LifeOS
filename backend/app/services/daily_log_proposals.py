"""Propose daily-log mutations from flexible check-in text."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models import Agent, DailyLogCreate
from app.services.provider_router import LLMProvidersExhaustedError, chat_completion

ALLOWED_KINDS = {"sleep", "meal", "protein", "training", "hydration", "shutdown", "family", "priority"}
CHECKIN_SIGNAL_RE = re.compile(
    r"\b("
    r"i|we|just|done|completed|finished|drank|drink|drnk|ate|eat|had|meal|water|cup|glass|"
    r"slept|sleep|woke|wokeup|wake|wake\s+up|bedtime|"
    r"shawarma|sandwich|sandwitch|trained|worked out|rested|sent|called|texted|messaged"
    r")\b",
    re.IGNORECASE,
)
COMPLETED_CHECKIN_RE = re.compile(
    r"\b(i|we|just)\s+(drank|drnk|ate|had|slept|woke|wokeup|trained|worked out|rested|sent|called|texted|messaged|finished|completed|did)\b|"
    r"\b(done|completed|finished)\b",
    re.IGNORECASE,
)
PLANNING_OR_QUESTION_RE = re.compile(
    r"\?|"
    r"^\s*(find|what|how|recommend|suggest|help me|can you|tell me|give me)\b|"
    r"\b(should|need to|plan to|want to|tomorrow|later|remind me|cheapest|budget|recipe|"
    r"meal i can make|max protein|more d[eé]tails?|details?|per ingr[eé]dient|ingredient price|price|cost)\b",
    re.IGNORECASE,
)
INFORMATION_REQUEST_RE = re.compile(
    r"\b("
    r"more d[eé]tails?|details?|explain|break down|recipe|ingredients?|ingr[eé]dients?|"
    r"per ingr[eé]dient|price|prices|cost|costs|how much|cheapest|budget"
    r")\b",
    re.IGNORECASE,
)
WATER_RE = re.compile(r"\b(water|hydration|drank|drink|drnk|cup|cups|glass|glasses|bottle|bottles)\b", re.IGNORECASE)
WATER_COUNT_RE = re.compile(r"\b(\d+)\s*(?:cup|cups|glass|glasses|bottle|bottles)\b", re.IGNORECASE)
SLEEP_WINDOW_RE = re.compile(
    r"\b(?:slept|sleep|went\s+to\s+bed|bedtime)\s*(?:at|around)?\s*"
    r"(?P<bed>\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)"
    r".{0,80}?\b(?:woke\s*up|wokeup|woke|wake\s*up|wake)\s*(?:at|around)?\s*"
    r"(?P<wake>\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"^\s*(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<suffix>a\.?m\.?|p\.?m\.?)?\s*$", re.IGNORECASE)
MEAL_RE = re.compile(
    r"\b(ate|eat|meal|breakfast|lunch|dinner|shawarma|sandwich|sandwitch|food)\b",
    re.IGNORECASE,
)
CONCRETE_MEAL_RE = re.compile(r"\b(meal|breakfast|lunch|dinner|shawarma|sandwich|sandwitch|food)\b", re.IGNORECASE)
PROTEIN_HIT_RE = re.compile(r"\b(enough protein|hit protein|protein hit|protein goal|protein target|got protein)\b", re.IGNORECASE)
TRAINING_RE = re.compile(r"\b(trained|workout|worked out|gym|walk|stretch|stretching)\b", re.IGNORECASE)
REST_RE = re.compile(r"\b(rested|rest day|explicit rest)\b", re.IGNORECASE)
FAMILY_RE = re.compile(r"\b(sent|called|texted|messaged|spoke)\b.*\b(mother|mom|father|dad|wife|family|parents)\b", re.IGNORECASE)
PRIORITY_RE = re.compile(r"\b(finished|completed|shipped|done)\b.*\b(priority|invoice|task|commitment)\b", re.IGNORECASE)
NEGATED_WATER_RE = re.compile(r"\b(no|not|didn'?t|did not|haven'?t|have not)\b.{0,24}\b(water|drink|drank|hydration)\b", re.IGNORECASE)
NEGATED_MEAL_RE = re.compile(r"\b(no|not|didn'?t|did not|haven'?t|have not)\b.{0,24}\b(ate|eat|meal|food)\b", re.IGNORECASE)
NEGATED_PROTEIN_RE = re.compile(r"\b(no|not|didn'?t|did not|haven'?t|have not)\b.{0,24}\b(protein)\b", re.IGNORECASE)
ONLY_KIND_PATTERNS: list[tuple[str, set[str]]] = [
    (r"\b(?:log|keep|count)?\s*only\s+(?:the\s+)?(?:water|hydration)\b|\b(?:water|hydration)\s+only\b", {"hydration"}),
    (r"\b(?:log|keep|count)?\s*only\s+(?:the\s+)?(?:meal|food|shawarma|sandwich|sandwitch)\b", {"meal"}),
    (r"\b(?:log|keep|count)?\s*only\s+(?:the\s+)?protein\b|\bprotein\s+only\b", {"protein"}),
]
EXCLUDE_KIND_PATTERNS: list[tuple[str, str]] = [
    ("meal", r"\b(remove|drop|skip|ignore|don'?t log|do not log|don'?t count|do not count)\b.{0,30}\b(meal|food|shawarma|sandwich|sandwitch)\b|\b(meal|food|shawarma|sandwich|sandwitch)\b.{0,30}\b(already counted|already logged)\b"),
    ("hydration", r"\b(remove|drop|skip|ignore|don'?t log|do not log|don'?t count|do not count)\b.{0,30}\b(water|hydration|drink|drank)\b|\b(water|hydration|drink|drank)\b.{0,30}\b(already counted|already logged)\b"),
    ("protein", r"\b(remove|drop|skip|ignore|don'?t log|do not log|don'?t count|do not count)\b.{0,30}\bprotein\b|\bprotein\b.{0,30}\b(already counted|already logged)\b"),
]


def _water_count(text: str) -> int:
    match = WATER_COUNT_RE.search(text)
    if not match:
        return 1
    return max(1, min(12, int(match.group(1))))


def _parse_clock_time(value: str, *, sleep_start: bool) -> tuple[int, str] | None:
    match = TIME_RE.match(value or "")
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    if hour > 23 or minute > 59:
        return None
    suffix = (match.group("suffix") or "").lower().replace(".", "")
    if suffix:
        if hour < 1 or hour > 12:
            return None
        if suffix == "pm" and hour != 12:
            hour += 12
        elif suffix == "am" and hour == 12:
            hour = 0
    elif sleep_start and 8 <= hour <= 11:
        hour += 12
    total = hour * 60 + minute
    return total, f"{hour % 24:02d}:{minute:02d}"


def _sleep_log(text: str) -> dict[str, Any] | None:
    match = SLEEP_WINDOW_RE.search(text)
    if not match:
        return None
    bed = _parse_clock_time(match.group("bed"), sleep_start=True)
    wake = _parse_clock_time(match.group("wake"), sleep_start=False)
    if not bed or not wake:
        return None
    bed_minutes, bedtime = bed
    wake_minutes, wake_time = wake
    wake_absolute = wake_minutes
    if wake_absolute <= bed_minutes:
        wake_absolute += 24 * 60
    hours = round((wake_absolute - bed_minutes) / 60, 2)
    if hours <= 0 or hours > 16:
        return None
    return {
        "kind": "sleep",
        "hours": hours,
        "bedtime": bedtime,
        "wake_time": wake_time,
        "note": text.strip()[:500],
    }


def _only_kinds(text: str) -> set[str] | None:
    for pattern, kinds in ONLY_KIND_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return set(kinds)
    return None


def _excluded_kinds(text: str) -> set[str]:
    excluded: set[str] = set()
    for kind, pattern in EXCLUDE_KIND_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            excluded.add(kind)
    if NEGATED_WATER_RE.search(text):
        excluded.add("hydration")
    if NEGATED_MEAL_RE.search(text):
        excluded.add("meal")
    if NEGATED_PROTEIN_RE.search(text):
        excluded.add("protein")
    return excluded


def _normalise_logs(
    raw_logs: Any,
    *,
    note: str,
    only_kinds: set[str] | None = None,
    excluded_kinds: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(raw_logs, list):
        return []
    excluded_kinds = excluded_kinds or set()
    logs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_logs:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in ALLOWED_KINDS:
            continue
        if only_kinds is not None and kind not in only_kinds:
            continue
        if kind in excluded_kinds:
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
        if kind == "sleep":
            if item.get("hours") is not None:
                try:
                    payload["hours"] = max(0.0, min(24.0, float(item.get("hours"))))
                except (TypeError, ValueError):
                    pass
            if item.get("bedtime"):
                payload["bedtime"] = str(item.get("bedtime"))
            if item.get("wake_time"):
                payload["wake_time"] = str(item.get("wake_time"))
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
    only_kinds = _only_kinds(text)
    excluded_kinds = _excluded_kinds(text)
    if only_kinds:
        excluded_kinds -= only_kinds
    protein_only = PROTEIN_HIT_RE.search(text) and not CONCRETE_MEAL_RE.search(text)
    sleep = _sleep_log(text)
    if sleep and "sleep" not in excluded_kinds:
        logs.append(sleep)
    if WATER_RE.search(text) and "hydration" not in excluded_kinds:
        logs.append({"kind": "hydration", "count": _water_count(text), "note": note})
    if protein_only and "protein" not in excluded_kinds:
        logs.append({"kind": "protein", "note": note})
    elif MEAL_RE.search(text) and "meal" not in excluded_kinds:
        logs.append({"kind": "meal", "count": 1, "note": note, "protein_hit": "protein" in text.lower()})
    if TRAINING_RE.search(text):
        logs.append({"kind": "training", "status": "done", "note": note})
    elif REST_RE.search(text):
        logs.append({"kind": "training", "status": "rest", "note": note})
    if FAMILY_RE.search(text):
        logs.append({"kind": "family", "done": True, "note": note})
    if PRIORITY_RE.search(text):
        logs.append({"kind": "priority", "count": 1, "note": note})
    return _normalise_logs(logs, note=note, only_kinds=only_kinds, excluded_kinds=excluded_kinds)


def _merge_logs(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(primary)
    seen = {str(item.get("kind")) for item in merged}
    for item in fallback:
        kind = str(item.get("kind"))
        if kind not in seen:
            merged.append(item)
            seen.add(kind)
    return merged


def _recent_context_text(context: list[dict[str, Any]] | None, *, limit: int = 6) -> str:
    if not context:
        return "none"
    lines: list[str] = []
    for item in context[-limit:]:
        role = str(item.get("role") or "unknown")
        content = str(item.get("content") or "").replace("\n", " ").strip()
        if content:
            lines.append(f"{role}: {content[:500]}")
    return "\n".join(lines) if lines else "none"


def _looks_like_information_request(message: str) -> bool:
    return bool(INFORMATION_REQUEST_RE.search(message or "")) and not COMPLETED_CHECKIN_RE.search(message or "")


async def propose_daily_log_payload(
    text: str,
    *,
    agent: Agent | None = None,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    message = str(text or "").strip()
    if not message:
        return None
    if _looks_like_information_request(message):
        return None
    if agent is None and not CHECKIN_SIGNAL_RE.search(message):
        return None
    if agent is None and PLANNING_OR_QUESTION_RE.search(message) and not COMPLETED_CHECKIN_RE.search(message):
        return None

    only_kinds = _only_kinds(message)
    excluded_kinds = _excluded_kinds(message)
    if only_kinds:
        excluded_kinds -= only_kinds
    protein_only = PROTEIN_HIT_RE.search(message) and not CONCRETE_MEAL_RE.search(message)
    if protein_only:
        logs = _fallback_logs(message)
        return {"logs": logs, "source_text": message} if logs else None

    fallback_logs = _fallback_logs(message)
    logs: list[dict[str, Any]] = []
    llm_succeeded = False
    llm_declined = False
    if agent:
        system = (
            "Classify the current user turn for LifeOS daily quick logs. "
            "Use recent context to distinguish a real completed check-in from a follow-up question about a prior answer. "
            "Return only JSON: {\"intent\":\"completed_checkin|correction|information_request|future_plan|none\",\"logs\":[...]}. "
            "Allowed log kinds: meal, protein, hydration, training, family, priority, shutdown, sleep. "
            "Use count for meal/hydration/priority, done for family/shutdown, status done/rest/missed for training, and hours/bedtime/wake_time for sleep. "
            "Infer from meaning, including typos and casual language, but log only real completed actions the user reports doing. "
            "If the user says only/keep/remove/already counted, obey that correction exactly. "
            "If they only say they hit enough protein, return protein and do not add meal. "
            "If the user mixes a question with completed status like slept/woke/drank/ate, extract only the completed status logs. "
            "If the user asks for advice, planning, recipe details, ingredient prices, budget options, or future actions, "
            "return intent=information_request and logs=[]. "
            "Example: after an assistant suggests an egg meal, user says 'more details for the egg meal, with per ingredient price' -> logs=[]. "
            "Example: user says 'I ate the egg meal' -> meal log. "
            "Do not explain. Do not include reasoning. JSON only."
        )
        user = (
            f"Recent context:\n{_recent_context_text(context)}\n\n"
            f"Current user message:\n{message}"
        )
        try:
            raw = await chat_completion(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
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
            intent = str(parsed.get("intent") or "").strip().lower()
            if intent in {"information_request", "future_plan", "none"}:
                llm_succeeded = True
                llm_declined = True
                logs = []
                return None
            llm_logs = _normalise_logs(
                parsed.get("logs"),
                note=message,
                only_kinds=only_kinds,
                excluded_kinds=excluded_kinds,
            )
            llm_succeeded = True
            llm_declined = not llm_logs
            logs = _merge_logs(llm_logs, fallback_logs)
        except (LLMProvidersExhaustedError, json.JSONDecodeError, ValueError, TypeError):
            logs = []
        except Exception:
            logs = []

    if llm_declined and PLANNING_OR_QUESTION_RE.search(message) and not COMPLETED_CHECKIN_RE.search(message):
        return None
    if not logs:
        logs = fallback_logs
    if not logs:
        return None
    return {"logs": logs, "source_text": message}


def format_daily_log_proposal(payload: dict[str, Any]) -> str:
    labels = []
    for item in payload.get("logs") or []:
        kind = item.get("kind")
        if kind in {"hydration", "meal", "priority"}:
            labels.append(f"{kind} x{item.get('count', 1)}")
        elif kind == "protein":
            labels.append("protein")
        elif kind == "sleep":
            hours = item.get("hours")
            bedtime = item.get("bedtime")
            wake_time = item.get("wake_time")
            if hours is not None:
                labels.append(f"sleep {hours:g}h ({bedtime or '?'}->{wake_time or '?'})")
            else:
                labels.append("sleep")
        elif kind == "training":
            labels.append(f"training:{item.get('status', 'done')}")
        elif kind in {"family", "shutdown"}:
            labels.append(kind)
        else:
            labels.append(str(kind))
    return ", ".join(labels)
