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
from app.services.deen_metrics import build_prayer_agent_context, build_weekly_deen_context
from app.services.discord_notify import send_channel_message_result
from app.services.action_executor import execute_pending_action
from app.services.events import publish_event
from app.services.intake import upsert_fallback_intake_entry, upsert_intake_entry_from_agent
from app.services.memory import get_context, save_message, summarise_session
from app.services.openviking_client import OpenVikingUnavailableError
from app.services.provider_router import LLMProvidersExhaustedError, chat_completion
from app.services.risk_engine import is_approval_eligible_action_type, should_require_approval
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
    r"google|internet|online"
    r")\b",
    re.IGNORECASE,
)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y at %H:%M UTC")


def _should_use_web_search(agent: Agent) -> bool:
    if agent.config_json and "use_web_search" in agent.config_json:
        return bool(agent.config_json["use_web_search"])
    return str(getattr(agent, "name", "") or "").strip().lower() != "sandbox"


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
    if _WORKSPACE_CONTEXT_PATTERN.search(user_message or ""):
        return False
    return bool(_EXTERNAL_INFO_PATTERN.search(user_message or ""))


def _should_fetch_shared_memory_context(agent_name: str, user_message: str, referenced_session_id: int | None) -> bool:
    if agent_name in {"intake-inbox", "commitment-capture", "commitment-coach"}:
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

_INTAKE_JSON_PATTERN = re.compile(
    r"\[INTAKE_JSON\]\s*(\{.*?\})\s*\[/INTAKE_JSON\]",
    re.IGNORECASE | re.DOTALL,
)
_INTAKE_JSON_OPEN_PATTERN = re.compile(
    r"\[INTAKE_JSON\]\s*(\{.*\})\s*$",
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
    if "[INTAKE_JSON]" not in text:
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
            cleaned = text.split("[INTAKE_JSON]", 1)[0].strip()
            return cleaned, payload, True
        cleaned = text.split("[INTAKE_JSON]", 1)[0].strip()
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
) -> dict:
    """Process user text through an agent with policy-based approvals."""
    active_session = None
    response_warnings: list[str] = []

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
            }
        if not agent.enabled:
            return {
                "response": f"Agent '{agent_name}' is disabled.",
                "pending_action_id": None,
                "risk_level": "low",
                "session_id": active_session.id if active_session else None,
                "session_title": active_session.title if active_session else None,
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
        )
        workspace_paths = get_agent_workspace_paths(agent)
        if agent.workspace_enabled:
            if _WORKSPACE_MUTATION_REQUEST_PATTERN.search(user_message or ""):
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
            if _should_search_web(agent, user_message, referenced_session_id):
                search_context = await _get_search_context(user_message)
                if search_context:
                    final_user_content = (
                        f"{final_user_content}\n\n"
                        f"{search_context}\n"
                        "Answer using provided real-time data where relevant."
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

        # Always persist the user turn immediately.
        try:
            await save_message(
                agent_name,
                "user",
                user_message,
                session_id=active_session.id if active_session else None,
            )
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
            "risk_level": risk_level,
            "session_id": active_session.id if active_session else None,
            "session_title": active_session.title if active_session else None,
            "warnings": response_warnings,
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
    if action.action_type in {"create_job", "create_agent", "workspace_delete"}:
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
    if run_result.get("error_code") in {"llm_unavailable", "memory_unavailable"}:
        logger.warning("Scheduled run skipped for '%s': %s", agent_name, run_result.get("error_code"))
        return {"status": "skipped", "reason": run_result.get("error_code")}
    if run_result.get("pending_action_id"):
        return {"status": "pending_approval", "pending_action_id": run_result["pending_action_id"]}
    notification_mode = str(notification_mode_override or "channel").strip().lower()
    if notification_mode == "silent":
        return {"status": "completed", "delivered": False}
    delivery = {"delivered": False, "channel_id": target_channel_id, "message_id": None}
    target_channel = target_channel_override or (agent.discord_channel if agent else None)
    target_channel_id = target_channel_id_override
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
    }
