"""Agent orchestrator - routing, approval policy, and scheduled nudges."""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.database import async_session
from app.models import ActionStatus, Agent, AuditLog, LifeItemCreate, PendingAction
from app.redaction import redact_sensitive
from app.services.chat_sessions import ensure_session, refresh_session_metadata
from app.services.deen_metrics import build_prayer_agent_context, build_weekly_deen_context
from app.services.discord_notify import send_channel_message
from app.services.action_executor import execute_pending_action
from app.services.events import publish_event
from app.services.memory import get_context, save_message, summarise_session
from app.services.provider_router import LLMProvidersExhaustedError, chat_completion
from app.services.risk_engine import classify_risk, infer_action_type, should_require_approval
from app.config import settings
from app.services.tools.web_search import web_search

logger = logging.getLogger(__name__)
LLM_UNAVAILABLE_MESSAGE = (
    "I couldn't generate a response right now because AI providers are temporarily unavailable. "
    "Please try again in a few minutes."
)
_NO_APPROVAL_AGENTS = {"daily-planner", "weekly-review"}


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y at %H:%M UTC")


def _should_use_web_search(agent: Agent) -> bool:
    if agent.config_json and "use_web_search" in agent.config_json:
        return bool(agent.config_json["use_web_search"])
    return True


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

        system_prompt = (
            f"{agent.system_prompt}\n\n"
            "--- SYSTEM INSTRUCTIONS ---\n"
            f"Current date/time: {_today_utc()}\n"
            "Use the date above for all date-sensitive responses.\n"
        )

        reporting_mode = agent_name in {"weekly-review", "daily-planner", "prayer-deen"}
        context = await get_context(
            agent_name,
            limit=20,
            session_id=active_session.id if active_session else None,
            apply_data_start_filter=reporting_mode,
        )
        messages = [{"role": "system", "content": system_prompt}, *context]

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
        if _should_use_web_search(agent):
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

        # Always persist the user turn immediately.
        await save_message(
            agent_name,
            "user",
            user_message,
            session_id=active_session.id if active_session else None,
        )
        # NOTE: The assistant message is saved here unconditionally so that the
        # conversation history stays coherent. If the corresponding action is
        # later rejected the agent will see its own "I will do X" in context —
        # this is intentional: it lets the agent know the action was proposed
        # and can be followed up. A future improvement is to tag pending
        # messages with a status flag and filter them in get_context.
        await save_message(
            agent_name,
            "assistant",
            response_text,
            session_id=active_session.id if active_session else None,
        )

        if active_session:
            active_session = await refresh_session_metadata(
                agent_name=agent_name,
                session_id=active_session.id,
            )
            if settings.memory_summarisation_enabled:
                async def _llm_for_summary(messages):
                    return await chat_completion(
                        messages,
                        provider=agent.provider,
                        model=agent.model,
                        fallback_provider=agent.fallback_provider,
                        fallback_model=agent.fallback_model,
                    )
                await summarise_session(
                    agent_name=agent_name,
                    session_id=active_session.id,
                    llm_call=_llm_for_summary,
                    threshold=settings.memory_summarisation_threshold,
                )

        # Extract and create goals from agent response
        await _extract_and_create_goals(response_text, agent_name)

        pending_id = None
        effective_approval_policy = "never" if agent_name in _NO_APPROVAL_AGENTS else approval_policy
        needs_approval, risk_level, action_type = should_require_approval(
            user_message=user_message,
            response_text=response_text,
            approval_policy=effective_approval_policy,
            require_approval=require_approval,
        )
        if needs_approval:
            pending = PendingAction(
                agent_name=agent_name,
                action_type=action_type,
                summary=response_text[:200],
                details=response_text,
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
            details=response_text[:1000],
            status="pending_approval" if pending_id else "completed",
        )
        db.add(audit)
        await db.commit()
        return {
            "response": response_text,
            "pending_action_id": pending_id,
            "risk_level": risk_level,
            "session_id": active_session.id if active_session else None,
            "session_title": active_session.title if active_session else None,
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
    if action.action_type in {"create_job", "create_agent"}:
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
) -> dict:
    """Execute a scheduled nudge and send it to the mapped Discord channel."""
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent or not agent.enabled:
            return {"status": "skipped", "reason": "agent_disabled_or_missing"}
        profile_prompt = prompt_override or (
            "Run your scheduled status check-in now. Keep it concise, supportive, and actionable. "
            "Do not execute external actions."
        )
    run_result = await handle_message(
        agent_name=agent_name,
        user_message=profile_prompt,
        approval_policy="auto",
        source="scheduler",
    )
    if run_result.get("error_code") == "llm_unavailable":
        logger.warning("Scheduled run skipped for '%s': all providers unavailable", agent_name)
        return {"status": "skipped", "reason": "llm_unavailable"}
    if run_result.get("pending_action_id"):
        return {"status": "pending_approval", "pending_action_id": run_result["pending_action_id"]}
    delivered = False
    target_channel = target_channel_override or (agent.discord_channel if agent else None)
    if target_channel:
        delivered = await send_channel_message(target_channel, run_result.get("response", ""))
    return {"status": "delivered" if delivered else "completed", "delivered": delivered}
