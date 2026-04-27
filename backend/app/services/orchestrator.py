"""Agent orchestrator - routing, approval policy, and scheduled nudges."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.database import async_session
from app.models import ActionStatus, Agent, AuditLog, LifeItemCreate, PendingAction
from app.redaction import redact_sensitive
from app.services.chat_sessions import build_session_reference_context, ensure_session, refresh_session_metadata
from app.services.daily_log_proposals import format_daily_log_proposal, propose_daily_log_payload
from app.services.deen_metrics import build_prayer_agent_context, build_weekly_deen_context
from app.services.discord_notify import send_channel_message_result
from app.services.action_executor import execute_pending_action
from app.services.agent_state import (
    AgentStateUnavailableError,
    build_agent_state_packet,
    grounding_metadata,
    render_agent_state_packet,
)
from app.services.events import publish_event
from app.services.intake import upsert_fallback_intake_entry, upsert_intake_entry_from_agent
from app.services.memory import get_context, save_message, summarise_session
from app.services.memory_ledger import maybe_record_user_turn, render_memory_ledger_context, search_memory_events
from app.services.openviking_client import OpenVikingUnavailableError
from app.services.provider_router import LLMProvidersExhaustedError, chat_completion
from app.services.risk_engine import is_approval_eligible_action_type, should_require_approval
from app.services.turn_planner import TurnPlan, plan_turn_for_tools
from app.services.workspace import (
    apply_workspace_actions,
    describe_workspace_listing_request,
    get_agent_workspace_paths,
    get_openviking_context,
    infer_workspace_actions_from_user_message,
    parse_workspace_actions,
    reject_workspace_delete_action,
    workspace_action_instructions,
    workspace_read_only_instructions,
)
from app.config import settings
from app.services.seed import SCHEDULED_PROMPTS
from app.services.shared_memory import build_shared_memory_context
from app.services.tools.web_search import web_search

logger = logging.getLogger(__name__)
LLM_UNAVAILABLE_MESSAGE = (
    "I couldn't generate a response right now because AI providers are temporarily unavailable. "
    "Please try again in a few minutes."
)
MEMORY_UNAVAILABLE_MESSAGE = (
    "OpenViking memory is currently unavailable, so this chat request could not be completed safely. "
    "Please retry after OpenViking is healthy again."
)
_NO_APPROVAL_AGENTS = {"daily-planner", "weekly-review"}
_WORKSPACE_REQUEST_PATTERN = re.compile(
    r"\b(file|workspace|directory|folder|write|create|save|edit|update|delete|remove|restore|\.md|\.txt)\b",
    re.IGNORECASE,
)
_WORKSPACE_MUTATION_REQUEST_PATTERN = re.compile(
    r"\b(write|create|save|edit|update|delete|remove|restore|rename|move|modify|patch)\b",
    re.IGNORECASE,
)
_WORKSPACE_SUCCESS_CLAIM_PATTERN = re.compile(
    r"\b(done|created|wrote|saved|updated|deleted|removed|restored|queued|submitted)\b",
    re.IGNORECASE,
)
_SESSION_REFERENCE_PATTERN = re.compile(r"\bsession\s*#?\s*(\d+)\b", re.IGNORECASE)
_LOCAL_CONTEXT_PATTERN = re.compile(
    r"\b("
    r"this session|current session|previous session|"
    r"previous message|last message|follow[- ]?up|"
    r"what did i just ask|what did i ask you to do|"
    r"what phrase did i ask you to remember|remember this exact phrase|"
    r"earlier in this session|just ask(?:ed)?"
    r")\b",
    re.IGNORECASE,
)
_WORKSPACE_CONTEXT_PATTERN = re.compile(
    r"(/[\w./-]+)|"
    r"\b(repo|repository|workspace|project|codebase|source code|code|file|files|folder|directory|docs|"
    r"document|module|class|function|readme|dockerfile|test|tests)\b|"
    r"(\.[A-Za-z0-9]{1,8}\b)",
    re.IGNORECASE,
)
_EXTERNAL_INFO_PATTERN = re.compile(
    r"\b("
    r"latest|current|today|news|weather|forecast|score|scores|stock|stocks|price|prices|market|"
    r"recent|up[- ]to[- ]date|breaking|headline|headlines|search the web|search web|look up|lookup|"
    r"cheap|cheapest|budget|cost|costs|available|availability|listing|listings|used|new|buy|deal|deals|"
    r"google|internet|online"
    r")\b",
    re.IGNORECASE,
)
_LIFEOS_PLANNING_REQUEST_PATTERN = re.compile(
    r"\b("
    r"what should i do today|what do i do today|plan my day|today'?s? plan|daily plan|"
    r"what should i focus on|what should i do next|how should i spend today"
    r")\b",
    re.IGNORECASE,
)
_DAILY_LOG_PROPOSAL_PATTERN = re.compile(
    r"\b(I can log this in Today|React with ✅|react with .? to apply|Please react with|proposed logging your|propose logging)\b",
    re.IGNORECASE,
)
_MEMORY_RECALL_QUERY_PATTERN = re.compile(
    r"\b("
    r"what\s+(?:did\s+i\s+say|did\s+i\s+mention|papers?|documents?|list|items?)|"
    r"what\s+.*\b(?:i\s+said|i\s+mentioned|i\s+need|from\s+hr)|"
    r"i\s+(?:do\s+not|don't|dont)\s+remember|"
    r"previous\s+(?:conversation|chat|message|capture)|"
    r"earlier\s+(?:conversation|chat|message|capture)"
    r")\b",
    re.IGNORECASE,
)
_LIST_ITEM_START_RE = re.compile(
    r"^(?:[-*]\s*)?(?:attestation|copie|copy|certificate|form|document|paper|liste\b)",
    re.IGNORECASE,
)
_PENDING_APPROVAL_MARKER_RE = re.compile(r"\[PENDING_APPROVAL\]", re.IGNORECASE)
_ACTION_CONFIRMATION_RE = re.compile(
    r"\b(yes|yep|yeah|proceed|go ahead|confirm|approve|approved|looks good|do it|apply|create it|submit it)\b",
    re.IGNORECASE,
)
_TASK_ADD_CONFIRMATION_RE = re.compile(
    r"\b(approved|approve|proceed|go ahead|do it|apply|create (?:it|them|the tasks?)|"
    r"add (?:it|them|the|these|those|two)|just add|submit (?:it|them))\b",
    re.IGNORECASE,
)
_TASK_CREATE_REQUEST_RE = re.compile(r"\b(create|add|track|make|remind).{0,40}\b(tasks?|reminders?)\b|\b(tasks?|reminders?).{0,40}\b(create|add|track|make)\b", re.IGNORECASE)
_DIRECT_LIFE_ACTION_PLANNER_RE = re.compile(
    r"\b(create|add|track|make).{0,80}\b(tasks?|reminders?|life items?|follow[- ]?ups?)\b|"
    r"\b(tasks?|reminders?|life items?|follow[- ]?ups?).{0,80}\b(create|add|track|make)\b|"
    r"\bremind me to\b",
    re.IGNORECASE,
)
_ACTION_NEGATION_RE = re.compile(r"\b(do not|don't|dont|no|not yet|hold off|cancel|stop)\b", re.IGNORECASE)
_STRUCTURED_LIFE_ACTION_TYPES = {"task_create", "life_item_create"}
_NATURAL_TASK_PROPOSAL_RE = re.compile(
    r"\b(proposed pending actions?|proposed pending approvals?|pending approvals?|to add these to (?:your )?lifeos)\b",
    re.IGNORECASE,
)
_TASK_FIELD_RE = re.compile(r"^(task|domain|due|notes?)\s*:\s*(.+)$", re.IGNORECASE)
_CANONICAL_DOMAINS = {"deen", "family", "work", "health", "planning"}
_PLANNING_CONTEXT_RE = re.compile(
    r"\b(admin|errand|event|wedding|appointment|paper|papers|document|documents|"
    r"contract|tax|hr|treasury|dgi|shop|store|pickup|pick up|drop off|ironing|"
    r"suit|clothes|clothing|uat|staging|notes?)\b",
    re.IGNORECASE,
)
_HEALTH_CONTEXT_RE = re.compile(r"\b(sleep|workout|gym|health|meal|protein|water|medicine|doctor)\b", re.IGNORECASE)
_FAMILY_CONTEXT_RE = re.compile(r"\b(wife|family|kids|mother|mom|mama|mum|father|dad|parent|brother|sister)\b", re.IGNORECASE)
_GREETING_ONLY_RE = re.compile(r"^\s*(hello|hi|hey|salam|salam alaikum|assalamu alaikum)[!. ]*\s*$", re.IGNORECASE)
_MONTH_DATE_RE = (
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
)
_CONVERSATIONAL_TASK_LINE_RE = re.compile(
    rf"^(?P<title>[^:\n]+?)\s+[–-]\s+(?P<timing>.*?{_MONTH_DATE_RE}.*)$",
    re.IGNORECASE,
)


def _profile_location_instruction(state_packet: dict | None) -> str:
    if not isinstance(state_packet, dict):
        return ""
    profile = state_packet.get("profile")
    if not isinstance(profile, dict):
        return ""
    city = str(profile.get("city") or "").strip()
    country = str(profile.get("country") or "").strip()
    timezone_name = str(profile.get("timezone") or "").strip()
    if not city and not country and not timezone_name:
        return ""
    location = ", ".join(part for part in [city, country] if part)
    parts = []
    if location:
        parts.append(f"Default user location is {location}.")
    if timezone_name:
        parts.append(f"Default user timezone is {timezone_name}.")
    parts.append(
        "Use that location for local recommendations, weather, availability, and budget advice unless the user names another place. "
        "Prefer local units/currency and do not default to US prices. "
        "For cheap meals, shopping, or budget advice, use local Morocco/Casablanca context and MAD when giving prices; "
        "if exact local prices are unavailable, say prices vary locally instead of using USD or US averages. "
        "Keep budget-food answers compact: no tables unless asked, usually 8 bullets or fewer."
    )
    return " ".join(parts)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y at %H:%M UTC")


def _should_use_web_search(agent: Agent) -> bool:
    if agent.config_json and "use_web_search" in agent.config_json:
        return bool(agent.config_json["use_web_search"])
    return True


def _extract_session_reference_id(text: str) -> int | None:
    match = _SESSION_REFERENCE_PATTERN.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _is_local_context_query(text: str) -> bool:
    return bool(_LOCAL_CONTEXT_PATTERN.search(text or ""))


def _should_fetch_workspace_context(user_message: str, referenced_session_id: int | None) -> bool:
    if referenced_session_id is not None or _is_local_context_query(user_message):
        return False
    return bool(_WORKSPACE_CONTEXT_PATTERN.search(user_message or ""))


def _should_search_web(agent: Agent, user_message: str, referenced_session_id: int | None) -> bool:
    if not _should_use_web_search(agent):
        return False
    if referenced_session_id is not None or _is_local_context_query(user_message):
        return False
    if _LIFEOS_PLANNING_REQUEST_PATTERN.search(user_message or ""):
        return False
    if _WORKSPACE_CONTEXT_PATTERN.search(user_message or ""):
        return False
    return bool(_EXTERNAL_INFO_PATTERN.search(user_message or ""))


def _can_use_turn_planner_for_search(agent: Agent, user_message: str, referenced_session_id: int | None) -> bool:
    if not _should_use_web_search(agent):
        return False
    if referenced_session_id is not None or _is_local_context_query(user_message):
        return False
    if _LIFEOS_PLANNING_REQUEST_PATTERN.search(user_message or ""):
        return False
    if _WORKSPACE_CONTEXT_PATTERN.search(user_message or ""):
        return False
    return True


def _should_fetch_shared_memory_context(agent_name: str, user_message: str, referenced_session_id: int | None) -> bool:
    if agent_name in {"commitment-capture", "commitment-coach"}:
        return False
    return referenced_session_id is None and not _is_local_context_query(user_message)


def _build_workspace_noop_response() -> str:
    return (
        "I haven't executed any workspace action yet. "
        "No files were created, updated, deleted, or restored because the reply did not include a valid "
        "[WORKSPACE_ACTIONS] block."
    )


def _append_response_notes(base_text: str, notes: list[str]) -> str:
    base = (base_text or "").strip()
    clean_notes = [str(note).strip() for note in notes if str(note).strip()]
    if not clean_notes:
        return base
    note_block = "\n".join(f"- {note}" for note in clean_notes)
    if not base:
        return f"Workspace update:\n{note_block}"
    return f"{base}\n\nWorkspace update:\n{note_block}"


def _append_unique_warning(warnings: list[str], warning: str) -> None:
    cleaned = str(warning or "").strip()
    if cleaned and cleaned not in warnings:
        warnings.append(cleaned)


def _is_daily_log_execution_note(note: str | None) -> bool:
    lowered = str(note or "").lower()
    return "daily log" in lowered and any(token in lowered for token in ("executed", "applied", "approval"))


def _filter_context_for_transient_note(
    context: list[dict[str, object]],
    transient_system_note: str | None,
) -> list[dict[str, object]]:
    if not context or not _is_daily_log_execution_note(transient_system_note):
        return context
    filtered: list[dict[str, object]] = []
    for message in context:
        if str(message.get("role") or "") == "assistant" and _DAILY_LOG_PROPOSAL_PATTERN.search(
            str(message.get("content") or "")
        ):
            continue
        filtered.append(message)
    return filtered


def _looks_like_memory_recall_query(text: str) -> bool:
    return bool(_MEMORY_RECALL_QUERY_PATTERN.search(text or ""))


def _extract_captured_list(raw_text: str) -> list[str]:
    lines = [line.strip(" \t-*•📌:") for line in str(raw_text or "").splitlines()]
    lines = [line for line in lines if line]
    collected: list[str] = []
    in_list = False
    for line in lines:
        lowered = line.lower()
        if "liste des documents" in lowered or "list of papers" in lowered or "papers to request" in lowered:
            in_list = True
            continue
        if in_list and _LIST_ITEM_START_RE.search(line):
            collected.append(line)
            continue
        if in_list and collected and not _LIST_ITEM_START_RE.search(line):
            break
    if len(collected) >= 2:
        return list(dict.fromkeys(collected))

    collapsed = re.sub(r"\s+", " ", str(raw_text or "")).strip()
    marker = re.search(r"(Attestation|Copie|Copy|Certificate|Form|Document|Paper)\b", collapsed, re.IGNORECASE)
    if not marker:
        return []
    tail = collapsed[marker.start() :]
    starts = list(re.finditer(r"\b(?:Attestation|Copie|Copy|Certificate|Form|Document|Paper)\b", tail, re.IGNORECASE))
    items: list[str] = []
    for idx, match in enumerate(starts):
        end = starts[idx + 1].start() if idx + 1 < len(starts) else len(tail)
        item = tail[match.start() : end].strip(" ;,.")
        if item:
            items.append(item)
    return list(dict.fromkeys(items)) if len(items) >= 2 else []


def _extract_followup_hint(raw_text: str) -> str:
    text = re.sub(r"\s+", " ", str(raw_text or "")).strip()
    match = re.search(r"Follow-up answer:\s*(.+)$", text, re.IGNORECASE)
    if not match:
        return ""
    hint = match.group(1).strip()
    return hint[:180]


def _hit_is_question_echo(user_message: str, hit: object) -> bool:
    raw_text = re.sub(r"\s+", " ", str(getattr(hit, "raw_text", "") or "")).strip().lower()
    snippet = re.sub(r"\s+", " ", str(getattr(hit, "snippet", "") or "")).strip().lower()
    query = re.sub(r"\s+", " ", str(user_message or "")).strip().lower()
    if not query:
        return False
    return raw_text == query or snippet == query


def _memory_recall_direct_answer(user_message: str, hits: list[object]) -> str | None:
    if not _looks_like_memory_recall_query(user_message) or not hits:
        return None
    non_echo_hits = [hit for hit in hits if not _hit_is_question_echo(user_message, hit)]
    for hit in non_echo_hits:
        raw_text = str(getattr(hit, "raw_text", "") or "")
        items = _extract_captured_list(raw_text)
        if items:
            lines = ["You said you need these from HR:"]
            lines.extend(f"- {item}" for item in items[:12])
            followup = _extract_followup_hint(raw_text)
            if followup:
                lines.append(f"\nFollow-up saved: {followup}")
            return "\n".join(lines)
    for hit in non_echo_hits:
        raw_text = str(getattr(hit, "raw_text", "") or "")
        snippet = str(getattr(hit, "snippet", "") or raw_text).strip()
        if snippet:
            return f"From memory, closest saved detail:\n{snippet[:900]}"
    return None


def _extract_pending_approval_payload(response_text: str) -> tuple[str, dict | None]:
    text = response_text or ""
    match = _PENDING_APPROVAL_MARKER_RE.search(text)
    if not match:
        return text.strip(), None
    before = text[: match.start()].strip()
    after = text[match.end() :].strip()
    try:
        payload, end_index = json.JSONDecoder().raw_decode(after)
    except json.JSONDecodeError:
        return before or text.strip(), None
    if not isinstance(payload, dict):
        return before or text.strip(), None
    tail = after[end_index:].strip()
    cleaned = "\n\n".join(part for part in [before, tail] if part).strip()
    return cleaned, payload


def _normalise_structured_action(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    action_type = str(payload.get("action_type") or "").strip().lower()
    if action_type not in _STRUCTURED_LIFE_ACTION_TYPES:
        return None
    details = payload.get("details")
    if not isinstance(details, dict):
        return None
    title = str(details.get("title") or payload.get("summary") or "").strip()
    if not title:
        return None
    return {
        "action_type": action_type,
        "summary": str(payload.get("summary") or f"Create task: {title}")[:200],
        "risk_level": str(payload.get("risk_level") or "low").strip().lower() or "low",
        "details": details,
    }


def _is_action_confirmation(user_message: str) -> bool:
    text = user_message or ""
    return bool(_ACTION_CONFIRMATION_RE.search(text)) and not bool(_ACTION_NEGATION_RE.search(text))


def _is_task_add_confirmation(user_message: str) -> bool:
    text = user_message or ""
    return bool(_TASK_ADD_CONFIRMATION_RE.search(text)) and not bool(_ACTION_NEGATION_RE.search(text))


def _looks_like_lifeos_task_request(user_message: str) -> bool:
    text = str(user_message or "")
    if not text or _ACTION_NEGATION_RE.search(text):
        return False
    if _WORKSPACE_CONTEXT_PATTERN.search(text):
        return False
    return bool(
        re.search(
            r"\b(task|tasks|reminder|reminders|remind me|commitment|commitments|today item|life item|follow[- ]?up)\b",
            text,
            re.IGNORECASE,
        )
    )


def _should_run_direct_life_action_planner(user_message: str) -> bool:
    text = str(user_message or "")
    if not text or _ACTION_NEGATION_RE.search(text):
        return False
    return bool(_DIRECT_LIFE_ACTION_PLANNER_RE.search(text))


def _format_structured_pending_response(action: dict, pending_id: int) -> str:
    details = action.get("details") or {}
    title = details.get("title") or action.get("summary") or "item"
    due_at = details.get("due_at")
    due_text = f" · due {due_at}" if due_at else ""
    return f"Ready to track: {title}{due_text}.\nApprove action #{pending_id} to apply it."


def _clean_natural_task_line(line: str) -> str:
    return re.sub(r"^[\s>*•\-📅👔💍]+", "", str(line or "")).strip()


def _normalise_life_domain(value: str | None, text: str = "") -> str:
    domain = re.sub(r"[^a-z]", "", str(value or "").lower())
    if domain in _CANONICAL_DOMAINS:
        lowered = str(text or "").lower()
        if domain == "health" and _PLANNING_CONTEXT_RE.search(lowered) and not _HEALTH_CONTEXT_RE.search(lowered):
            return "planning"
        if domain == "family" and _PLANNING_CONTEXT_RE.search(lowered) and not _FAMILY_CONTEXT_RE.search(lowered):
            return "planning"
        return domain
    if domain in {"personal", "admin", "errand", "event", "events"}:
        return "planning"
    return "planning"


def _parse_due_value(value: str) -> str | None:
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", str(value or "")).strip()
    cleaned = cleaned.replace(" @ ", "T").replace(" at ", "T")
    iso_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{1,2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?", cleaned)
    if iso_match:
        due = iso_match.group(0).replace("Z", "+00:00")
        if re.match(r"\d{4}-\d{2}-\d{2}T\d{1}:", due):
            due = due[:11] + "0" + due[11:]
        if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?:[+-]\d{2}:\d{2})$", due):
            due = f"{due[:16]}:00{due[16:]}"
        elif re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", due):
            due = f"{due}:00"
        return due
    return None


def _normalise_structured_actions(actions: list[dict]) -> list[dict]:
    normalised: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for action in actions:
        item = _normalise_structured_action(action)
        if not item:
            continue
        details = dict(item["details"])
        domain_text = " ".join(str(details.get(key) or "") for key in ("title", "summary", "notes", "desired_outcome", "next_action"))
        details["domain"] = _normalise_life_domain(details.get("domain"), domain_text)
        details.setdefault("kind", "task")
        details.setdefault("priority", "medium")
        key = (str(details.get("title") or "").strip().lower(), str(details.get("due_at") or ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        item["details"] = details
        normalised.append(item)
    return normalised


def _extract_natural_task_actions_from_text(text: str) -> list[dict]:
    if not _NATURAL_TASK_PROPOSAL_RE.search(text or ""):
        return []
    actions: list[dict] = []
    current: dict[str, object] | None = None
    for raw_line in str(text or "").splitlines():
        line = _clean_natural_task_line(raw_line)
        if not line:
            continue
        match = _TASK_FIELD_RE.match(line)
        if not match:
            continue
        field = match.group(1).lower()
        value = match.group(2).strip()
        if field == "task":
            if current and current.get("title"):
                actions.append(
                    {
                        "action_type": "task_create",
                        "summary": f"Create task: {current['title']}",
                        "risk_level": "low",
                        "details": current,
                    }
                )
            current = {"title": value, "kind": "task", "priority": "medium", "domain": "planning"}
            continue
        if not current:
            continue
        if field == "domain":
            current["domain"] = _normalise_life_domain(value)
        elif field == "due":
            due_at = _parse_due_value(value)
            if due_at:
                current["due_at"] = due_at
        elif field.startswith("note"):
            current["notes"] = value
    if current and current.get("title"):
        actions.append(
            {
                "action_type": "task_create",
                "summary": f"Create task: {current['title']}",
                "risk_level": "low",
                "details": current,
            }
        )
    return _normalise_structured_actions(actions)


def _extract_latest_task_actions_from_context(context: list[dict[str, object]] | None) -> list[dict]:
    for message in reversed(context or []):
        if str(message.get("role") or "") != "assistant":
            continue
        actions = _extract_natural_task_actions_from_text(str(message.get("content") or ""))
        if actions:
            return actions
    return []


def _assistant_greeting_reply(agent_name: str, user_message: str) -> str | None:
    if agent_name == "work-ai-influencer" and _GREETING_ONLY_RE.match(user_message or ""):
        return "Hello. I can help with work tasks, AI content ideas, or recalling prior work details from LifeOS memory."
    return None


def _parse_month_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%B %d, %Y")
    except (TypeError, ValueError):
        return None


def _date_iso(value: datetime, hour: int) -> str:
    return f"{value.strftime('%Y-%m-%d')}T{hour:02d}:00:00+01:00"


def _parse_due_from_timing_text(timing_text: str) -> str | None:
    date_match = re.search(_MONTH_DATE_RE, timing_text or "", re.IGNORECASE)
    if not date_match:
        return None
    day = _parse_month_date(date_match.group(0))
    if not day:
        return None
    lowered = str(timing_text or "").lower()
    hour = 10 if "morning" in lowered or "am" in lowered else 12
    return _date_iso(day, hour)


def _extract_conversational_task_actions_from_context(context: list[dict[str, object]] | None) -> list[dict]:
    for message in reversed(context or []):
        if str(message.get("role") or "") != "assistant":
            continue
        content = str(message.get("content") or "")
        if not re.search(r"\b(task|tasks|reminder|reminders)\b", content, re.IGNORECASE):
            continue
        raw_actions: list[dict] = []
        for raw_line in content.splitlines():
            line = _clean_natural_task_line(raw_line)
            match = _CONVERSATIONAL_TASK_LINE_RE.match(line)
            if not match:
                continue
            title = match.group("title").strip()
            due_at = _parse_due_from_timing_text(match.group("timing"))
            if not title or not due_at:
                continue
            raw_actions.append(
                {
                    "action_type": "task_create",
                    "summary": f"Create task: {title}",
                    "risk_level": "low",
                    "details": {
                        "title": title,
                        "domain": "planning",
                        "kind": "task",
                        "priority": "medium",
                        "due_at": due_at,
                        "notes": match.group("timing").strip(),
                    },
                }
            )
        actions = _normalise_structured_actions(raw_actions)
        if actions:
            return actions
    return []


def _extract_json_object(raw: str) -> dict | None:
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _plan_direct_life_actions(
    *,
    agent: Agent,
    user_message: str,
    state_packet: dict | None,
    context: list[dict[str, object]] | None,
) -> list[dict]:
    profile = state_packet.get("profile") if isinstance(state_packet, dict) else {}
    system = (
        "You are LifeOS direct action planner. Detect only explicit requests to create/add/track a LifeOS task, "
        "reminder, commitment, or follow-up. Return JSON only.\n"
        "Schema: {\"intent\":\"task_create|none\",\"actions\":[{\"action_type\":\"task_create\","
        "\"summary\":\"Create task: ...\",\"risk_level\":\"low\",\"details\":{\"title\":\"...\","
        "\"domain\":\"deen|family|work|health|planning\",\"kind\":\"task\",\"priority\":\"low|medium|high\","
        "\"due_at\":\"ISO-8601 with timezone offset or null\",\"notes\":\"...\"}}]}.\n"
        "Use intent none for advice, questions, workspace/file mutations, deletion, external messages, purchases, daily logs, or ambiguous wishes. "
        "Use planning for admin, errands, events, HR/tax paperwork, UAT/staging review notes, and personal logistics. "
        "Resolve relative dates from current date/time and profile timezone. Do not ask for approval; explicit low-risk LifeOS tracking may execute now. "
        "Treat words like staging, UAT, notes, docs, or test as ordinary task content unless the user clearly asks to mutate files/workspace."
    )
    user = (
        f"Current UTC datetime: {_today_utc()}\n"
        f"Profile JSON: {json.dumps(profile if isinstance(profile, dict) else {}, ensure_ascii=True)}\n"
        f"Recent context JSON: {json.dumps((context or [])[-6:], ensure_ascii=True, default=str)[:4000]}\n\n"
        f"User message:\n{user_message}"
    )
    try:
        raw = await chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            provider=agent.provider,
            model=agent.model,
            fallback_provider=agent.fallback_provider,
            fallback_model=agent.fallback_model,
            temperature=0.0,
            max_tokens=700,
        )
    except Exception:
        return []
    payload = _extract_json_object(raw)
    if not payload or str(payload.get("intent") or "").strip().lower() != "task_create":
        return []
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list):
        return []
    return _normalise_structured_actions([action for action in raw_actions if isinstance(action, dict)])


async def _execute_structured_actions_now(*, actions: list[dict], agent_name: str, source: str) -> tuple[bool, str]:
    messages: list[str] = []
    ok_all = True
    for action in actions:
        details_text = json.dumps(action["details"], ensure_ascii=True)
        pending = PendingAction(
            agent_name=agent_name,
            action_type=action["action_type"],
            summary=action["summary"],
            details=details_text,
            status=ActionStatus.APPROVED,
            risk_level=action["risk_level"],
            reviewed_by=source,
            review_source=source,
        )
        ok, result = await execute_pending_action(pending)
        ok_all = ok_all and ok
        messages.append(result if ok else f"Could not apply {action['summary']}: {result}")
    return ok_all, "\n".join(messages)


def _memory_unavailable_result(active_session, exc: Exception) -> dict:
    safe_error = redact_sensitive(str(exc))
    return {
        "response": f"{MEMORY_UNAVAILABLE_MESSAGE}\n\nDetails: {safe_error}",
        "pending_action_id": None,
        "risk_level": "high",
        "error_code": "memory_unavailable",
        "session_id": active_session.id if active_session else None,
        "session_title": active_session.title if active_session else None,
    }


async def _get_search_context(query: str) -> str:
    try:
        results = await web_search(query, max_results=5)
        if not results:
            return ""
        lines = ["[WEB SEARCH RESULTS - use these for up-to-date information]"]
        for i, result in enumerate(results, 1):
            lines.append(f"{i}. **{result['title']}**")
            lines.append(f"   URL: {result['url']}")
            lines.append(f"   {result['snippet']}")
            lines.append("")
        lines.append("[END OF SEARCH RESULTS]")
        return "\n".join(lines)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Web search failed, proceeding without context: %s", exc)
        return ""


_GOAL_PATTERN = re.compile(
    r"\[GOAL\]\s*"
    r'title\s*=\s*"([^"]+)"'
    r'(?:\s+domain\s*=\s*"([^"]+)")?'
    r'(?:\s+priority\s*=\s*"([^"]+)")?'
    r'(?:\s+start_date\s*=\s*"([^"]+)")?'
    r"\s*\[/GOAL\]",
    re.IGNORECASE,
)

_INTAKE_BLOCK_NAME = r"(?:INTAKE_JSON|RAW_LIFE_SYNTHESIS_JSON)"
_INTAKE_JSON_PATTERN = re.compile(
    rf"\[{_INTAKE_BLOCK_NAME}\]\s*(\{{.*?\}})\s*\[/({_INTAKE_BLOCK_NAME})\]",
    re.IGNORECASE | re.DOTALL,
)
_INTAKE_JSON_OPEN_PATTERN = re.compile(
    rf"\[{_INTAKE_BLOCK_NAME}\]\s*(\{{.*\}})\s*$",
    re.IGNORECASE | re.DOTALL,
)
_INTAKE_AGENTS = {"intake-inbox", "commitment-capture"}


async def _extract_and_create_goals(response_text: str, agent_name: str) -> list[dict]:
    """Parse [GOAL] blocks from agent response and create LifeItems."""
    from app.services.life import create_life_item

    created = []
    for match in _GOAL_PATTERN.finditer(response_text):
        title = match.group(1)
        domain = match.group(2) or "planning"
        priority = match.group(3) or "medium"
        start_date = match.group(4) or None
        try:
            item_data = LifeItemCreate(
                domain=domain,
                title=title,
                kind="goal",
                priority=priority,
                source_agent=agent_name,
                start_date=start_date,
            )
            item = await create_life_item(item_data)
            created.append({"id": item.id, "title": item.title, "domain": item.domain})
            logger.info("agent_created_goal agent=%s title=%s id=%d", agent_name, title, item.id)
        except Exception:
            logger.exception("Failed to create goal from agent response (title=%r)", title)
    return created


def _extract_intake_payload(response_text: str) -> tuple[str, dict | None, bool]:
    text = response_text or ""
    if "[INTAKE_JSON]" not in text and "[RAW_LIFE_SYNTHESIS_JSON]" not in text:
        return text.strip(), None, False

    match = _INTAKE_JSON_PATTERN.search(text)
    if not match:
        open_match = _INTAKE_JSON_OPEN_PATTERN.search(text)
        if open_match:
            try:
                payload = json.loads(open_match.group(1))
            except json.JSONDecodeError:
                logger.warning("Invalid unterminated INTAKE_JSON block; leaving response unstructured")
                payload = None
            cleaned = re.split(r"\[(?:INTAKE_JSON|RAW_LIFE_SYNTHESIS_JSON)\]", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            return cleaned, payload, True
        cleaned = re.split(r"\[(?:INTAKE_JSON|RAW_LIFE_SYNTHESIS_JSON)\]", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        return cleaned, None, True

    payload = None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("Invalid INTAKE_JSON block; leaving response unstructured")

    cleaned = _INTAKE_JSON_PATTERN.sub("", text).strip()
    return cleaned, payload, True


async def _extract_and_upsert_intake_entry(
    *,
    agent_name: str,
    response_text: str,
    user_message: str,
    session_id: int | None,
) -> dict | None:
    if agent_name not in _INTAKE_AGENTS:
        return None

    cleaned_text, payload, saw_machine_block = _extract_intake_payload(response_text)
    if payload:
        entry = await upsert_intake_entry_from_agent(
            payload=payload,
            user_message=user_message,
            response_text=cleaned_text,
            agent_name=agent_name,
            session_id=session_id,
        )
    else:
        entry = await upsert_fallback_intake_entry(
            user_message=user_message,
            response_text=cleaned_text,
            agent_name=agent_name,
            session_id=session_id,
            reason="invalid_or_partial_intake_json" if saw_machine_block else "missing_intake_json",
        )
    return {"cleaned_text": cleaned_text, "entry_id": entry.id}


def _agent_temperature(agent: Agent) -> float:
    raw = (agent.config_json or {}).get("temperature", 0.7)
    try:
        return max(0.0, min(float(raw), 1.5))
    except (TypeError, ValueError):
        return 0.7


def _agent_max_tokens(agent: Agent) -> int:
    raw = (agent.config_json or {}).get("max_tokens", 1024)
    try:
        return max(256, min(int(raw), 4096))
    except (TypeError, ValueError):
        return 1024


async def handle_message(
    agent_name: str,
    user_message: str,
    approval_policy: str = "auto",
    require_approval: Optional[bool] = None,
    source: str = "api",
    session_id: Optional[int] = None,
    session_enabled: bool = False,
    transient_system_note: Optional[str] = None,
) -> dict:
    """Process user text through an agent with policy-based approvals."""
    active_session = None
    response_warnings: list[str] = []
    state_packet: dict | None = None
    grounding: dict = {"grounded": False, "sources": []}
    context: list[dict[str, object]] | None = None

    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent:
            return {
                "response": f"Agent '{agent_name}' not found.",
                "pending_action_id": None,
                "risk_level": "low",
                "session_id": active_session.id if active_session else None,
                "session_title": active_session.title if active_session else None,
                "grounding": grounding,
            }
        if not agent.enabled:
            return {
                "response": f"Agent '{agent_name}' is disabled.",
                "pending_action_id": None,
                "risk_level": "low",
                "session_id": active_session.id if active_session else None,
                "session_title": active_session.title if active_session else None,
                "grounding": grounding,
            }

        if session_enabled:
            try:
                active_session = await ensure_session(agent_name=agent_name, session_id=session_id)
            except ValueError as exc:
                return {
                    "response": str(exc),
                    "pending_action_id": None,
                    "risk_level": "low",
                    "error_code": "session_not_found",
                    "grounding": grounding,
                }

        referenced_session_id = _extract_session_reference_id(user_message)
        referenced_session_context = ""
        response_text: str | None = None
        if referenced_session_id is not None and (active_session is None or referenced_session_id != active_session.id):
            try:
                referenced_session_context = await build_session_reference_context(
                    agent_name=agent_name,
                    session_id=referenced_session_id,
                )
            except ValueError:
                response_text = (
                    f"I couldn't find `{agent_name}` session #{referenced_session_id}. "
                    f"Use `!sessions {agent_name}` to list available session ids."
                )
            except OpenVikingUnavailableError as exc:
                logger.error(
                    "Referenced session lookup unavailable for agent '%s': %s",
                    agent_name,
                    redact_sensitive(str(exc)),
                )
                return _memory_unavailable_result(active_session, exc)

        system_prompt = (
            f"{agent.system_prompt}\n\n"
            "--- SYSTEM INSTRUCTIONS ---\n"
            f"Current date/time: {_today_utc()}\n"
            "Use the date above for all date-sensitive responses.\n"
            "Never reveal hidden chain-of-thought, scratchpad reasoning, tool-selection reasoning, or self-talk. "
            "Do not start final answers with internal narration like 'Okay, the user...' or 'I need to...'. "
            "Give the final useful answer only.\n"
        )
        if _should_use_web_search(agent):
            system_prompt = (
                f"{system_prompt}"
                "Web search is available for current external facts like weather, prices, news, and latest information. "
                "When web search results are provided, use them and cite URLs from the search context. "
                "Do not claim you have no internet access; say web search failed only if no search context is available.\n"
            )
        else:
            system_prompt = (
                f"{system_prompt}"
                "Web search is disabled for this agent unless search results are explicitly provided in the prompt.\n"
            )
        if transient_system_note:
            system_prompt = (
                f"{system_prompt}\n"
                "--- TRANSIENT TURN CONTEXT ---\n"
                f"{str(transient_system_note).strip()[:1200]}\n"
            )
            if _is_daily_log_execution_note(transient_system_note):
                system_prompt = (
                    f"{system_prompt}"
                    "Ignore stale assistant daily-log proposal messages in chat memory; the approval already executed. "
                    "Do not ask the user to confirm that same log again and do not describe it as merely proposed.\n"
                )
        try:
            state_packet = await build_agent_state_packet(
                agent=agent,
                user_message=user_message,
                source=source,
            )
            grounding = grounding_metadata(state_packet)
            system_prompt = f"{system_prompt}\n{render_agent_state_packet(state_packet)}\n"
            profile_instruction = _profile_location_instruction(state_packet)
            if profile_instruction:
                system_prompt = f"{system_prompt}\n--- USER LOCAL CONTEXT ---\n{profile_instruction}\n"
            for warning in grounding.get("warnings") or []:
                _append_unique_warning(response_warnings, warning)
        except AgentStateUnavailableError as exc:
            safe_error = redact_sensitive(str(exc))
            grounding = grounding_metadata(None, error=safe_error)
            return {
                "response": (
                    "I could not answer safely because the LifeOS state packet is unavailable. "
                    "Please retry after Today/status context is healthy.\n\n"
                    f"Details: {safe_error}"
                ),
                "pending_action_id": None,
                "risk_level": "high",
                "error_code": "state_packet_unavailable",
                "session_id": active_session.id if active_session else None,
                "session_title": active_session.title if active_session else None,
                "warnings": response_warnings,
                "grounding": grounding,
            }
        daily_log_payload = None
        if response_text is None and not _is_daily_log_execution_note(transient_system_note):
            reporting_mode = agent_name in {"weekly-review", "daily-planner", "prayer-deen"}
            if active_session:
                try:
                    context = await get_context(
                        agent_name,
                        limit=20,
                        session_id=active_session.id,
                        apply_data_start_filter=reporting_mode,
                    )
                except OpenVikingUnavailableError as exc:
                    logger.warning(
                        "Memory context unavailable for daily-log classifier on agent '%s'; continuing without session context: %s",
                        agent_name,
                        redact_sensitive(str(exc)),
                    )
                    _append_unique_warning(
                        response_warnings,
                        "OpenViking memory was unavailable for this turn, so the quick-log classifier ran without prior session context.",
                    )
                    context = []
            direct_actions = []
            direct_life_planner_used = agent_name not in _INTAKE_AGENTS and _should_run_direct_life_action_planner(user_message)
            if direct_life_planner_used:
                direct_actions = await _plan_direct_life_actions(
                    agent=agent,
                    user_message=user_message,
                    state_packet=state_packet,
                    context=context or [],
                )
            if direct_actions:
                execution_ok, execution_result = await _execute_structured_actions_now(
                    actions=direct_actions,
                    agent_name=agent_name,
                    source=source,
                )
                response_text = execution_result if execution_ok else f"Some tasks could not be applied:\n{execution_result}"
            elif agent_name not in _INTAKE_AGENTS and not direct_life_planner_used:
                daily_log_payload = await propose_daily_log_payload(user_message, agent=agent, context=context or [])
        if daily_log_payload:
            proposal = format_daily_log_proposal(daily_log_payload)
            final_response_text = (
                f"I can log this in Today: {proposal}.\n\n"
                "React with ✅ to apply it. If it is wrong, reply to this bot message with the corrected details."
            )
            pending = PendingAction(
                agent_name=agent_name,
                action_type="daily_log_batch",
                summary=f"Proposed daily log: {proposal}"[:200],
                details=json.dumps(daily_log_payload, ensure_ascii=True),
                status=ActionStatus.PENDING,
                risk_level="low",
            )
            db.add(pending)
            await db.commit()
            await db.refresh(pending)
            await publish_event(
                "approvals.pending.updated",
                {"kind": "approval", "id": str(pending.id)},
                {"action_id": pending.id, "status": pending.status.value, "agent_name": pending.agent_name},
            )
            db.add(
                AuditLog(
                    agent_name=agent_name,
                    action="chat:daily_log_batch",
                    details=final_response_text[:1000],
                    status="pending_approval",
                )
            )
            await db.commit()
            try:
                await save_message(
                    agent_name,
                    "user",
                    user_message,
                    session_id=active_session.id if active_session else None,
                )
                await save_message(
                    agent_name,
                    "assistant",
                    final_response_text,
                    session_id=active_session.id if active_session else None,
                )
            except OpenVikingUnavailableError as exc:
                logger.warning(
                    "Daily-log proposal persistence unavailable for agent '%s': %s",
                    agent_name,
                    redact_sensitive(str(exc)),
                )
                _append_unique_warning(
                    response_warnings,
                    "This turn could not be saved to OpenViking session memory, so session history may look incomplete until memory is healthy again.",
                )
            if active_session:
                try:
                    active_session = await refresh_session_metadata(
                        agent_name=agent_name,
                        session_id=active_session.id,
                    )
                except OpenVikingUnavailableError as exc:
                    logger.warning(
                        "Session metadata refresh skipped for agent '%s' because OpenViking was unavailable: %s",
                        agent_name,
                        redact_sensitive(str(exc)),
                    )
            return {
                "response": final_response_text,
                "pending_action_id": pending.id,
                "pending_action_type": "daily_log_batch",
                "risk_level": "low",
                "session_id": active_session.id if active_session else None,
                "session_title": active_session.title if active_session else None,
                "warnings": response_warnings,
                "grounding": grounding,
            }
        workspace_paths = get_agent_workspace_paths(agent)
        if agent.workspace_enabled:
            if _WORKSPACE_MUTATION_REQUEST_PATTERN.search(user_message or "") and not _looks_like_lifeos_task_request(user_message):
                system_prompt = (
                    f"{system_prompt}\n"
                    "--- WORKSPACE ACCESS ---\n"
                    f"{workspace_action_instructions(agent_name, workspace_paths)}\n"
                )
            else:
                system_prompt = (
                    f"{system_prompt}\n"
                    "--- WORKSPACE ACCESS ---\n"
                    f"{workspace_read_only_instructions(workspace_paths)}\n"
                )
            if response_text is None:
                response_text = describe_workspace_listing_request(user_message, workspace_paths)

        if response_text is None:
            reporting_mode = agent_name in {"weekly-review", "daily-planner", "prayer-deen"}
            if context is None:
                try:
                    context = await get_context(
                        agent_name,
                        limit=20,
                        session_id=active_session.id if active_session else None,
                        apply_data_start_filter=reporting_mode,
                    )
                except OpenVikingUnavailableError as exc:
                    logger.warning(
                        "Memory context unavailable for agent '%s'; continuing without session context: %s",
                        agent_name,
                        redact_sensitive(str(exc)),
                    )
                    _append_unique_warning(
                        response_warnings,
                        "OpenViking memory was unavailable for this turn, so the reply was generated without prior session context.",
                    )
                    context = []
            try:
                ledger_hits_for_turn = await search_memory_events(query=user_message, agent=agent, limit=6)
                direct_memory_answer = _memory_recall_direct_answer(user_message, ledger_hits_for_turn)
            except Exception as exc:
                logger.warning("Direct memory recall failed for agent '%s': %s", agent_name, exc)
                ledger_hits_for_turn = []
                direct_memory_answer = None
            if direct_memory_answer:
                response_text = direct_memory_answer
            if response_text is None:
                response_text = _assistant_greeting_reply(agent_name, user_message)
            if response_text is None and (
                _is_task_add_confirmation(user_message)
                or _looks_like_lifeos_task_request(user_message)
                or _TASK_CREATE_REQUEST_RE.search(user_message or "")
                or _ACTION_CONFIRMATION_RE.search(user_message or "")
            ):
                context_actions = _extract_latest_task_actions_from_context(context)
                if not context_actions:
                    context_actions = _extract_conversational_task_actions_from_context(context)
                if context_actions:
                    execution_ok, execution_result = await _execute_structured_actions_now(
                        actions=context_actions,
                        agent_name=agent_name,
                        source=source,
                    )
                    response_text = execution_result if execution_ok else f"Some tasks could not be applied:\n{execution_result}"
                elif _should_run_direct_life_action_planner(user_message):
                    direct_actions = await _plan_direct_life_actions(
                        agent=agent,
                        user_message=user_message,
                        state_packet=state_packet,
                        context=context,
                    )
                    if direct_actions:
                        execution_ok, execution_result = await _execute_structured_actions_now(
                            actions=direct_actions,
                            agent_name=agent_name,
                            source=source,
                        )
                        response_text = execution_result if execution_ok else f"Some tasks could not be applied:\n{execution_result}"
            if response_text is None:
                turn_plan = TurnPlan()
                turn_planner_used = False
                if _can_use_turn_planner_for_search(agent, user_message, referenced_session_id):
                    turn_planner_used = True
                    turn_plan = await plan_turn_for_tools(
                        agent=agent,
                        user_message=user_message,
                        context=context,
                        current_datetime=_today_utc(),
                        state_packet=state_packet,
                    )
                context = _filter_context_for_transient_note(context, transient_system_note)
                messages = [{"role": "system", "content": system_prompt}, *context]
                if referenced_session_context:
                    messages.append({"role": "system", "content": referenced_session_context})

                final_user_content = user_message
                if agent_name == "prayer-deen":
                    try:
                        prayer_context = await build_prayer_agent_context()
                        final_user_content = f"{prayer_context}\n\nUser Query: {user_message}"
                    except Exception as exc:
                        logger.warning("Failed building prayer context: %s", exc)
                elif agent_name == "weekly-review":
                    try:
                        deen_context = await build_weekly_deen_context()
                        final_user_content = (
                            f"{deen_context}\n\n"
                            "Include a dedicated Deen section with prayer accuracy, retroactive logs, Quran, tahajjud, and adhkar.\n\n"
                            f"User Query: {user_message}"
                        )
                    except Exception as exc:
                        logger.warning("Failed building weekly deen context: %s", exc)
                if _should_fetch_shared_memory_context(agent_name, user_message, referenced_session_id):
                    try:
                        shared_memory_context = await build_shared_memory_context(
                            agent=agent,
                            query=user_message,
                        )
                    except OpenVikingUnavailableError as exc:
                        logger.warning(
                            "Shared-memory retrieval unavailable for agent '%s'; continuing without optional context: %s",
                            agent_name,
                            redact_sensitive(str(exc)),
                        )
                        shared_memory_context = ""
                    except Exception as exc:
                        logger.warning("Shared-memory context failed for agent '%s': %s", agent_name, exc)
                        shared_memory_context = ""
                    if shared_memory_context:
                        final_user_content = f"{shared_memory_context}\n\n{final_user_content}"
                ledger_context = render_memory_ledger_context(ledger_hits_for_turn)
                if ledger_context:
                    final_user_content = f"{ledger_context}\n\n{final_user_content}"
                if agent.workspace_enabled and _should_fetch_workspace_context(user_message, referenced_session_id):
                    try:
                        openviking_context = await get_openviking_context(
                            agent_name=agent_name,
                            query=user_message,
                            session_id=active_session.id if active_session else None,
                            workspace_paths=workspace_paths,
                        )
                    except OpenVikingUnavailableError as exc:
                        logger.warning(
                            "Workspace retrieval unavailable for agent '%s'; continuing without optional context: %s",
                            agent_name,
                            redact_sensitive(str(exc)),
                        )
                        openviking_context = ""
                    if openviking_context:
                        final_user_content = f"{openviking_context}\n\n{final_user_content}"
                search_query = None
                if turn_plan.needs_web_search and turn_plan.web_search_query:
                    search_query = turn_plan.web_search_query
                elif not turn_planner_used and _should_search_web(agent, user_message, referenced_session_id):
                    search_query = user_message
                if search_query:
                    search_context = await _get_search_context(search_query)
                    if search_context:
                        final_user_content = (
                            f"{final_user_content}\n\n"
                            f"Web search query used: {search_query}\n"
                            f"{search_context}\n"
                            "Answer using provided real-time data where relevant. "
                            "Include a short Sources section with the URLs you used."
                        )
                    else:
                        final_user_content = (
                            f"{final_user_content}\n\n"
                            f"Web search query attempted: {search_query}\n"
                            "No web search results were returned. Say that search returned no usable results; do not guess."
                        )
                messages.append({"role": "user", "content": final_user_content})

                try:
                    response_text = await chat_completion(
                        messages=messages,
                        provider=agent.provider,
                        model=agent.model,
                        fallback_provider=agent.fallback_provider,
                        fallback_model=agent.fallback_model,
                        temperature=_agent_temperature(agent),
                        max_tokens=_agent_max_tokens(agent),
                    )
                except LLMProvidersExhaustedError as exc:
                    logger.error("LLM providers exhausted for agent '%s': %s", agent_name, redact_sensitive(str(exc)))
                    return {
                        "response": LLM_UNAVAILABLE_MESSAGE,
                        "pending_action_id": None,
                        "risk_level": "high",
                        "error_code": "llm_unavailable",
                        "session_id": active_session.id if active_session else None,
                        "session_title": active_session.title if active_session else None,
                        "grounding": grounding,
                    }
                except Exception as exc:
                    safe_error = redact_sensitive(str(exc))
                    logger.error("LLM call failed for agent '%s': %s", agent_name, safe_error)
                    return {
                        "response": f"LLM error: {safe_error}",
                        "pending_action_id": None,
                        "risk_level": "high",
                        "session_id": active_session.id if active_session else None,
                        "session_title": active_session.title if active_session else None,
                        "grounding": grounding,
                    }

        cleaned_response, workspace_envelope = parse_workspace_actions(response_text)
        intake_result = await _extract_and_upsert_intake_entry(
            agent_name=agent_name,
            response_text=cleaned_response,
            user_message=user_message,
            session_id=active_session.id if active_session else None,
        )
        if intake_result:
            cleaned_response = intake_result["cleaned_text"]
        cleaned_response, pending_payload = _extract_pending_approval_payload(cleaned_response)
        machine_actions = _normalise_structured_actions([pending_payload]) if pending_payload else []
        natural_actions = _extract_natural_task_actions_from_text(cleaned_response)
        inferred_workspace_action = False
        if (
            agent.workspace_enabled
            and (workspace_envelope is None or not workspace_envelope.actions)
        ):
            inferred_envelope = infer_workspace_actions_from_user_message(user_message)
            if inferred_envelope and inferred_envelope.actions:
                workspace_envelope = inferred_envelope
                inferred_workspace_action = True
                first_action = inferred_envelope.actions[0]
                if first_action.type == "delete_file":
                    cleaned_response = (
                        f"I'll queue the requested delete for approval: `{first_action.path}`."
                    )

        workspace_notes: list[str] = []
        pending_id = None
        workspace_action_type = None
        workspace_risk_level = "low"
        if workspace_envelope and workspace_envelope.actions:
            if agent.workspace_enabled:
                try:
                    workspace_result = await apply_workspace_actions(
                        agent_name=agent_name,
                        workspace_paths=workspace_paths,
                        envelope=workspace_envelope,
                    )
                    workspace_notes.extend(workspace_result.notes)
                    pending_id = workspace_result.pending_action_id
                    workspace_action_type = "workspace_delete" if pending_id else "workspace_mutation"
                    workspace_risk_level = "high" if pending_id else "low"
                except Exception as exc:
                    logger.exception("Workspace action execution failed for %s", agent_name)
                    workspace_notes.append(f"Workspace action failed: {exc}")
                    workspace_action_type = "workspace_error"
                    workspace_risk_level = "high"
            else:
                workspace_notes.append(
                    "Workspace actions were ignored because workspace access is disabled for this agent."
                )
                workspace_action_type = "workspace_mutation_denied"
                workspace_risk_level = "medium"
        elif (
            agent.workspace_enabled
            and not inferred_workspace_action
            and _WORKSPACE_REQUEST_PATTERN.search(user_message)
            and _WORKSPACE_SUCCESS_CLAIM_PATTERN.search(cleaned_response)
        ):
            cleaned_response = _build_workspace_noop_response()

        final_response_text = _append_response_notes(cleaned_response, workspace_notes)

        structured_action_handled = False
        actions_to_apply = machine_actions or (natural_actions if _is_task_add_confirmation(user_message) else [])
        if actions_to_apply and all(is_approval_eligible_action_type(action["action_type"]) for action in actions_to_apply):
            structured_action_handled = True
            action_type = actions_to_apply[0]["action_type"]
            risk_level = actions_to_apply[0]["risk_level"]
            should_execute = _is_action_confirmation(user_message) if machine_actions else _is_task_add_confirmation(user_message)
            if should_execute:
                execution_ok, execution_result = await _execute_structured_actions_now(
                    actions=actions_to_apply,
                    agent_name=agent_name,
                    source=source,
                )
                final_response_text = (
                    execution_result if execution_ok else f"Some tasks could not be applied:\n{execution_result}"
                )
                if not execution_ok:
                    risk_level = "medium"
            else:
                queued_lines: list[str] = []
                for action in actions_to_apply:
                    pending = PendingAction(
                        agent_name=agent_name,
                        action_type=action["action_type"],
                        summary=action["summary"],
                        details=json.dumps(action["details"], ensure_ascii=True),
                        status=ActionStatus.PENDING,
                        risk_level=action["risk_level"],
                    )
                    db.add(pending)
                    await db.commit()
                    await db.refresh(pending)
                    pending_id = pending_id or pending.id
                    await publish_event(
                        "approvals.pending.updated",
                        {"kind": "approval", "id": str(pending.id)},
                        {"action_id": pending.id, "status": pending.status.value, "agent_name": pending.agent_name},
                    )
                    queued_lines.append(_format_structured_pending_response(action, pending.id))
                final_response_text = "\n".join(queued_lines)

        # Always persist the user turn immediately.
        try:
            await save_message(
                agent_name,
                "user",
                user_message,
                session_id=active_session.id if active_session else None,
            )
            try:
                await maybe_record_user_turn(
                    user_message=user_message,
                    agent_name=agent_name,
                    session_id=active_session.id if active_session else None,
                    source=source,
                )
            except Exception as exc:
                logger.warning("Memory ledger write skipped for agent '%s': %s", agent_name, redact_sensitive(str(exc)))
        except OpenVikingUnavailableError as exc:
            logger.warning(
                "User message persistence unavailable for agent '%s'; returning unsaved response: %s",
                agent_name,
                redact_sensitive(str(exc)),
            )
            _append_unique_warning(
                response_warnings,
                "This turn could not be saved to OpenViking session memory, so session history may look incomplete until memory is healthy again.",
            )
        try:
            # NOTE: The assistant message is saved here unconditionally so that the
            # conversation history stays coherent. If the corresponding action is
            # later rejected the agent will see its own "I will do X" in context -
            # this is intentional: it lets the agent know the action was proposed
            # and can be followed up. A future improvement is to tag pending
            # messages with a status flag and filter them in get_context.
            await save_message(
                agent_name,
                "assistant",
                final_response_text,
                session_id=active_session.id if active_session else None,
            )
        except OpenVikingUnavailableError as exc:
            logger.warning(
                "Assistant message persistence unavailable for agent '%s'; returning unsaved response: %s",
                agent_name,
                redact_sensitive(str(exc)),
            )
            _append_unique_warning(
                response_warnings,
                "This turn could not be saved to OpenViking session memory, so session history may look incomplete until memory is healthy again.",
            )

        if active_session:
            try:
                active_session = await refresh_session_metadata(
                    agent_name=agent_name,
                    session_id=active_session.id,
                )
            except OpenVikingUnavailableError as exc:
                logger.warning(
                    "Session metadata refresh skipped for agent '%s' because OpenViking was unavailable: %s",
                    agent_name,
                    redact_sensitive(str(exc)),
                )
            if settings.memory_summarisation_enabled:
                async def _llm_for_summary(messages):
                    return await chat_completion(
                        messages,
                        provider=agent.provider,
                        model=agent.model,
                        fallback_provider=agent.fallback_provider,
                        fallback_model=agent.fallback_model,
                        temperature=_agent_temperature(agent),
                        max_tokens=_agent_max_tokens(agent),
                    )
                try:
                    await summarise_session(
                        agent_name=agent_name,
                        session_id=active_session.id,
                        llm_call=_llm_for_summary,
                        threshold=settings.memory_summarisation_threshold,
                    )
                except OpenVikingUnavailableError as exc:
                    logger.warning(
                        "Session summary refresh skipped for agent '%s' because OpenViking was unavailable: %s",
                        agent_name,
                        redact_sensitive(str(exc)),
                    )

        # Extract and create goals from agent response
        await _extract_and_create_goals(cleaned_response, agent_name)

        if workspace_action_type:
            risk_level = workspace_risk_level
            action_type = workspace_action_type
        elif structured_action_handled:
            pass
        else:
            effective_approval_policy = "never" if agent_name in _NO_APPROVAL_AGENTS else approval_policy
            needs_approval, risk_level, action_type = should_require_approval(
                user_message=user_message,
                response_text=final_response_text,
                approval_policy=effective_approval_policy,
                require_approval=require_approval,
            )
            if needs_approval and is_approval_eligible_action_type(action_type):
                pending = PendingAction(
                    agent_name=agent_name,
                    action_type=action_type,
                    summary=final_response_text[:200],
                    details=final_response_text,
                    status=ActionStatus.PENDING,
                    risk_level=risk_level,
                )
                db.add(pending)
                await db.commit()
                await db.refresh(pending)
                pending_id = pending.id
                await publish_event(
                    "approvals.pending.updated",
                    {"kind": "approval", "id": str(pending.id)},
                    {"action_id": pending.id, "status": pending.status.value, "agent_name": pending.agent_name},
                )

        logger.info(
            "orchestrator_result agent=%s action_type=%s risk=%s pending=%s",
            agent_name,
            action_type,
            risk_level,
            bool(pending_id),
        )

        audit = AuditLog(
            agent_name=agent_name,
            action=f"{source}:{action_type}",
            details=final_response_text[:1000],
            status="pending_approval" if pending_id else "completed",
        )
        db.add(audit)
        await db.commit()
        return {
            "response": final_response_text,
            "pending_action_id": pending_id,
            "pending_action_type": action_type if pending_id else None,
            "risk_level": risk_level,
            "session_id": active_session.id if active_session else None,
            "session_title": active_session.title if active_session else None,
            "warnings": response_warnings,
            "grounding": grounding,
        }


async def approve_action(action_id: int, reviewer: Optional[str] = None, source: str = "api") -> Optional[PendingAction]:
    async with async_session() as db:
        result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
        action = result.scalar_one_or_none()
        if not action or action.status != ActionStatus.PENDING:
            return None
        action.status = ActionStatus.APPROVED
        action.resolved_at = datetime.now(timezone.utc)
        action.reviewed_by = reviewer
        action.review_source = source
        db.add(
            AuditLog(
                agent_name=action.agent_name,
                action=f"approved:{action.action_type}",
                details=action.summary[:500],
                status="approved",
            )
        )
        await db.commit()
    execution_ok = False
    execution_result = ""
    if action.action_type in {"create_job", "create_agent", "workspace_delete", "daily_log_batch", "life_item_create", "task_create"}:
        execution_ok, execution_result = await execute_pending_action(action)
        async with async_session() as db:
            result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
            refreshed = result.scalar_one_or_none()
            if refreshed:
                refreshed.status = ActionStatus.EXECUTED if execution_ok else ActionStatus.FAILED
                refreshed.result = execution_result
                db.add(
                    AuditLog(
                        agent_name=refreshed.agent_name,
                        action=f"execute:{refreshed.action_type}",
                        details=execution_result[:500],
                        status="executed" if execution_ok else "failed",
                    )
                )
                await db.commit()
                action = refreshed
    if action:
        await publish_event(
            "approvals.decided",
            {"kind": "approval", "id": str(action.id)},
            {"action_id": action.id, "status": action.status.value, "reviewed_by": action.reviewed_by},
        )
        await publish_event(
            "approvals.pending.updated",
            {"kind": "approval", "id": str(action.id)},
            {"action_id": action.id, "status": action.status.value},
        )
    return action


async def reject_action(
    action_id: int,
    reason: str = "",
    reviewer: Optional[str] = None,
    source: str = "api",
) -> Optional[PendingAction]:
    async with async_session() as db:
        result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
        action = result.scalar_one_or_none()
        if not action or action.status != ActionStatus.PENDING:
            return None
        action.status = ActionStatus.REJECTED
        action.resolved_at = datetime.now(timezone.utc)
        action.result = reason
        action.reviewed_by = reviewer
        action.review_source = source
        db.add(
            AuditLog(
                agent_name=action.agent_name,
                action=f"rejected:{action.action_type}",
                details=reason[:500],
                status="rejected",
            )
        )
        await db.commit()
        if action.action_type == "workspace_delete":
            await reject_workspace_delete_action(action.id, reason=reason)
        await publish_event(
            "approvals.decided",
            {"kind": "approval", "id": str(action.id)},
            {"action_id": action.id, "status": action.status.value, "reviewed_by": action.reviewed_by},
        )
        await publish_event(
            "approvals.pending.updated",
            {"kind": "approval", "id": str(action.id)},
            {"action_id": action.id, "status": action.status.value},
        )
        return action


async def get_all_agents() -> list[Agent]:
    async with async_session() as db:
        result = await db.execute(select(Agent).order_by(Agent.id))
        return list(result.scalars().all())


async def run_scheduled_agent(
    agent_name: str,
    prompt_override: str | None = None,
    target_channel_override: str | None = None,
    target_channel_id_override: str | None = None,
    notification_mode_override: str | None = None,
) -> dict:
    """Execute a scheduled nudge and send it to the mapped Discord channel."""
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent or not agent.enabled:
            return {"status": "skipped", "reason": "agent_disabled_or_missing"}
        profile_prompt = prompt_override or (
            SCHEDULED_PROMPTS.get(agent_name)
            or "Run your scheduled status check-in now. Keep it concise, supportive, and actionable. "
            "Do not execute external actions."
        )
    run_result = await handle_message(
        agent_name=agent_name,
        user_message=profile_prompt,
        approval_policy="auto",
        source="scheduler",
    )
    if run_result.get("error_code") in {"llm_unavailable", "memory_unavailable", "state_packet_unavailable"}:
        logger.warning("Scheduled run skipped for '%s': %s", agent_name, run_result.get("error_code"))
        return {"status": "skipped", "reason": run_result.get("error_code")}
    if run_result.get("pending_action_id"):
        return {"status": "pending_approval", "pending_action_id": run_result["pending_action_id"]}
    notification_mode = str(notification_mode_override or "channel").strip().lower()
    if notification_mode == "silent":
        return {"status": "completed", "delivered": False}
    target_channel = target_channel_override or (agent.discord_channel if agent else None)
    target_channel_id = target_channel_id_override
    delivery = {"delivered": False, "channel_id": target_channel_id, "message_id": None}
    if target_channel_id or target_channel:
        delivery = await send_channel_message_result(
            target_channel,
            run_result.get("response", ""),
            channel_id=target_channel_id,
        )
    delivered = bool(delivery.get("delivered"))
    return {
        "status": "delivered" if delivered else "completed",
        "delivered": delivered,
        "notification_channel": target_channel,
        "notification_channel_id": delivery.get("channel_id") or target_channel_id,
        "notification_message_id": delivery.get("message_id"),
        "grounding": run_result.get("grounding") or {},
    }
