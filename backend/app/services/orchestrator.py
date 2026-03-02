"""Agent orchestrator - routing, approval policy, and scheduled nudges."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.database import async_session
from app.models import ActionStatus, Agent, AuditLog, PendingAction
from app.services.deen_metrics import build_prayer_agent_context, build_weekly_deen_context
from app.services.discord_notify import send_channel_message
from app.services.memory import get_context, save_message
from app.services.provider_router import chat_completion
from app.services.tools.web_search import web_search

logger = logging.getLogger(__name__)

LOW_RISK_KEYWORDS = {
    "status",
    "summary",
    "explain",
    "advice",
    "check-in",
    "checkin",
}
MEDIUM_RISK_KEYWORDS = {
    "remind",
    "commitment",
    "deadline",
    "schedule",
    "plan",
    "promise",
    "follow up",
}
HIGH_RISK_KEYWORDS = {
    "send email",
    "book",
    "purchase",
    "pay",
    "external api",
    "execute",
    "delete",
}


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y at %H:%M UTC")


def _should_use_web_search(agent: Agent) -> bool:
    if agent.config_json and "use_web_search" in agent.config_json:
        return bool(agent.config_json["use_web_search"])
    return True


def classify_risk(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in HIGH_RISK_KEYWORDS):
        return "high"
    if any(keyword in lowered for keyword in MEDIUM_RISK_KEYWORDS):
        return "medium"
    if any(keyword in lowered for keyword in LOW_RISK_KEYWORDS):
        return "low"
    return "low"


def infer_action_type(text: str) -> str:
    lowered = text.lower()
    if "status" in lowered or "summary" in lowered:
        return "status"
    if "check-in" in lowered or "checkin" in lowered:
        return "check-in"
    if "remind" in lowered:
        return "reminder"
    if "commitment" in lowered or "promise" in lowered:
        return "commitment"
    if "deadline" in lowered:
        return "deadline"
    return "message"


def should_require_approval(
    user_message: str,
    response_text: str,
    approval_policy: str = "auto",
    require_approval: Optional[bool] = None,
) -> tuple[bool, str, str]:
    if require_approval is True:
        risk_level = classify_risk(f"{user_message}\n{response_text}")
        return True, risk_level, infer_action_type(user_message)
    if require_approval is False and approval_policy == "never":
        return False, "low", infer_action_type(user_message)
    if approval_policy == "always":
        risk_level = classify_risk(f"{user_message}\n{response_text}")
        return True, risk_level, infer_action_type(user_message)
    if approval_policy == "never":
        return False, "low", infer_action_type(user_message)

    action_type = infer_action_type(user_message)
    risk_level = classify_risk(f"{action_type}\n{user_message}\n{response_text}")
    needs_approval = risk_level in {"medium", "high"} and action_type not in {"status", "check-in"}
    return needs_approval, risk_level, action_type


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


async def handle_message(
    agent_name: str,
    user_message: str,
    approval_policy: str = "auto",
    require_approval: Optional[bool] = None,
    source: str = "api",
) -> dict:
    """Process user text through an agent with policy-based approvals."""
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent:
            return {"response": f"Agent '{agent_name}' not found.", "pending_action_id": None, "risk_level": "low"}
        if not agent.enabled:
            return {
                "response": f"Agent '{agent_name}' is disabled.",
                "pending_action_id": None,
                "risk_level": "low",
            }

        system_prompt = (
            f"{agent.system_prompt}\n\n"
            "--- SYSTEM INSTRUCTIONS ---\n"
            f"Current date/time: {_today_utc()}\n"
            "Use the date above for all date-sensitive responses.\n"
        )

        context = await get_context(agent_name, limit=20)
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
        except Exception as exc:
            logger.error("LLM call failed for agent '%s': %s", agent_name, exc)
            return {"response": f"LLM error: {exc}", "pending_action_id": None, "risk_level": "high"}

        await save_message(agent_name, "user", user_message)
        await save_message(agent_name, "assistant", response_text)

        pending_id = None
        needs_approval, risk_level, action_type = should_require_approval(
            user_message=user_message,
            response_text=response_text,
            approval_policy=approval_policy,
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
        return {"response": response_text, "pending_action_id": pending_id, "risk_level": risk_level}


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
        return action


async def get_all_agents() -> list[Agent]:
    async with async_session() as db:
        result = await db.execute(select(Agent).order_by(Agent.id))
        return list(result.scalars().all())


async def run_scheduled_agent(agent_name: str) -> dict:
    """Execute a scheduled nudge and send it to the mapped Discord channel."""
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent or not agent.enabled:
            return {"status": "skipped", "reason": "agent_disabled_or_missing"}
        profile_prompt = (
            "Run your scheduled status check-in now. Keep it concise, supportive, and actionable. "
            "Do not execute external actions."
        )
    run_result = await handle_message(
        agent_name=agent_name,
        user_message=profile_prompt,
        approval_policy="auto",
        source="scheduler",
    )
    if run_result.get("pending_action_id"):
        return {"status": "pending_approval", "pending_action_id": run_result["pending_action_id"]}
    delivered = False
    if agent and agent.discord_channel:
        delivered = await send_channel_message(agent.discord_channel, run_result.get("response", ""))
    return {"status": "delivered" if delivered else "completed", "delivered": delivered}
