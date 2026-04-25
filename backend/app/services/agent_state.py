"""Canonical state packet for grounded agent replies."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import ActionStatus, Agent, JobRunLog, PendingAction, SharedMemoryProposal
from app.redaction import redact_sensitive
from app.services.openviking_client import OpenVikingUnavailableError


class AgentStateUnavailableError(RuntimeError):
    """Raised when required LifeOS status cannot be loaded safely."""


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _life_item_brief(item: Any) -> dict[str, Any]:
    return {
        "id": _get(item, "id"),
        "title": _get(item, "title"),
        "domain": _get(item, "domain"),
        "kind": _get(item, "kind"),
        "priority": _get(item, "priority"),
        "status": _get(item, "status"),
        "due_at": _get(item, "due_at"),
        "priority_score": _get(item, "priority_score"),
        "priority_reason": _get(item, "priority_reason"),
        "focus_reason": _get(item, "focus_reason"),
        "follow_up_due_at": _get(item, "follow_up_due_at"),
    }


def _intake_brief(entry: Any) -> dict[str, Any]:
    return {
        "id": getattr(entry, "id", None),
        "title": getattr(entry, "title", None) or getattr(entry, "raw_text", None),
        "status": getattr(entry, "status", None),
        "domain": getattr(entry, "domain", None),
        "kind": getattr(entry, "kind", None),
        "follow_up_questions": list(getattr(entry, "follow_up_questions_json", None) or []),
        "created_at": getattr(entry, "created_at", None),
        "updated_at": getattr(entry, "updated_at", None),
    }


def _proposal_brief(proposal: SharedMemoryProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "title": proposal.title,
        "domain": proposal.domain,
        "scope": proposal.scope,
        "status": proposal.status,
        "target_path": proposal.target_path,
        "created_at": proposal.created_at,
    }


def _approval_brief(action: PendingAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "agent_name": action.agent_name,
        "action_type": action.action_type,
        "summary": action.summary,
        "risk_level": action.risk_level,
        "created_at": action.created_at,
    }


def _job_failure_brief(run: JobRunLog) -> dict[str, Any]:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "status": run.status,
        "message": run.message,
        "error": redact_sensitive(run.error or ""),
        "finished_at": run.finished_at,
    }


def _profile_brief(profile: Any) -> dict[str, Any]:
    return {
        "timezone": profile.timezone,
        "city": profile.city,
        "country": profile.country,
        "work_shift_start": profile.work_shift_start,
        "work_shift_end": profile.work_shift_end,
        "quiet_hours_start": profile.quiet_hours_start,
        "quiet_hours_end": profile.quiet_hours_end,
        "nudge_mode": profile.nudge_mode,
        "sleep_bedtime_target": profile.sleep_bedtime_target,
        "sleep_wake_target": profile.sleep_wake_target,
        "sleep_caffeine_cutoff": profile.sleep_caffeine_cutoff,
    }


def _settings_brief(settings_row: Any) -> dict[str, Any]:
    return {
        "data_start_date": settings_row.data_start_date,
        "default_timezone": settings_row.default_timezone,
        "autonomy_enabled": settings_row.autonomy_enabled,
        "approval_required_for_mutations": settings_row.approval_required_for_mutations,
    }


def _scorecard_brief(scorecard: Any) -> dict[str, Any] | None:
    if not scorecard:
        return None
    return {
        "local_date": getattr(scorecard, "local_date", None),
        "sleep_hours": getattr(scorecard, "sleep_hours", None),
        "meals_count": getattr(scorecard, "meals_count", None),
        "hydration_count": getattr(scorecard, "hydration_count", None),
        "training_status": getattr(scorecard, "training_status", None),
        "shutdown_done": getattr(scorecard, "shutdown_done", None),
        "protein_hit": getattr(scorecard, "protein_hit", None),
        "family_action_done": getattr(scorecard, "family_action_done", None),
        "top_priority_completed_count": getattr(scorecard, "top_priority_completed_count", None),
        "rescue_status": getattr(scorecard, "rescue_status", None),
    }


async def build_agent_state_packet(*, agent: Agent, user_message: str, source: str) -> dict[str, Any]:
    """Build the strict status packet every agent must ground on."""
    from app.services.life import get_today_agenda
    from app.services.profile import get_or_create_profile
    from app.services.shared_memory import search_shared_memory
    from app.services.system_settings import get_or_create_system_settings

    warnings: list[str] = []
    try:
        agenda = await get_today_agenda()
        profile = await get_or_create_profile()
        settings_row = await get_or_create_system_settings()
    except Exception as exc:
        raise AgentStateUnavailableError(redact_sensitive(str(exc))) from exc

    async with async_session() as db:
        approvals_result = await db.execute(
            select(PendingAction)
            .where(PendingAction.status == ActionStatus.PENDING)
            .order_by(PendingAction.created_at.desc(), PendingAction.id.desc())
            .limit(5)
        )
        proposals_result = await db.execute(
            select(SharedMemoryProposal)
            .where(SharedMemoryProposal.status == "pending")
            .order_by(SharedMemoryProposal.created_at.desc(), SharedMemoryProposal.id.desc())
            .limit(5)
        )
        job_failures_result = await db.execute(
            select(JobRunLog)
            .where(JobRunLog.status.in_(["failed", "error"]))
            .order_by(JobRunLog.finished_at.desc(), JobRunLog.id.desc())
            .limit(5)
        )

        pending_approvals = list(approvals_result.scalars().all())
        memory_review = list(proposals_result.scalars().all())
        recent_job_failures = list(job_failures_result.scalars().all())

    memory_hits: list[dict[str, Any]] = []
    if (user_message or "").strip():
        try:
            hits = await search_shared_memory(query=user_message, agent=agent)
            memory_hits = [
                {
                    "title": hit.title,
                    "path": hit.path,
                    "scope": hit.scope,
                    "domain": hit.domain,
                    "source": hit.source,
                    "score": hit.score,
                    "snippet": hit.snippet,
                    "uri": hit.uri,
                }
                for hit in hits[:5]
            ]
        except OpenVikingUnavailableError as exc:
            warnings.append(f"shared_memory_unavailable: {redact_sensitive(str(exc))}")
        except Exception as exc:
            warnings.append(f"shared_memory_error: {redact_sensitive(str(exc))}")

    packet = {
        "grounded": True,
        "strict": True,
        "generated_at": datetime.now(timezone.utc),
        "agent_name": agent.name,
        "source": source,
        "sources": [
            "today_agenda",
            "user_profile",
            "system_settings",
            "pending_approvals",
            "memory_review",
            "recent_job_failures",
            "shared_memory_search",
        ],
        "today": {
            "timezone": agenda["timezone"],
            "now": agenda["now"],
            "top_focus": [_life_item_brief(item) for item in agenda.get("top_focus") or []],
            "due_today": [_life_item_brief(item) for item in agenda.get("due_today") or []],
            "overdue": [_life_item_brief(item) for item in agenda.get("overdue") or []],
            "domain_summary": agenda.get("domain_summary") or {},
            "scorecard": _scorecard_brief(agenda.get("scorecard")),
            "next_prayer": agenda.get("next_prayer"),
            "rescue_plan": agenda.get("rescue_plan"),
            "sleep_protocol": agenda.get("sleep_protocol"),
            "streaks": agenda.get("streaks") or [],
            "trend_summary": agenda.get("trend_summary"),
        },
        "capture_review": {
            "summary": agenda.get("intake_summary") or {},
            "needs_answer": [_intake_brief(entry) for entry in agenda.get("ready_intake") or []],
        },
        "memory_review": [_proposal_brief(row) for row in memory_review],
        "pending_approvals": [_approval_brief(row) for row in pending_approvals],
        "recent_job_failures": [_job_failure_brief(row) for row in recent_job_failures],
        "profile": _profile_brief(profile),
        "settings": _settings_brief(settings_row),
        "shared_memory_hits": memory_hits,
        "warnings": warnings,
    }
    return packet


def grounding_metadata(packet: dict[str, Any] | None, *, error: str | None = None) -> dict[str, Any]:
    if not packet:
        return {"grounded": False, "sources": [], "error": error}
    return {
        "grounded": bool(packet.get("grounded")),
        "strict": bool(packet.get("strict")),
        "generated_at": _json_default(packet.get("generated_at")),
        "sources": list(packet.get("sources") or []),
        "warnings": list(packet.get("warnings") or []),
        "memory_hits": len(packet.get("shared_memory_hits") or []),
    }


def render_agent_state_packet(packet: dict[str, Any]) -> str:
    rendered = json.dumps(packet, default=_json_default, ensure_ascii=True, indent=2)
    return (
        "--- LIFEOS STATE PACKET: STRICT SOURCE OF TRUTH ---\n"
        f"{rendered}\n\n"
        "--- GROUNDING RULES ---\n"
        "- Use the state packet above as the source of truth for the user's status, tasks, habits, commitments, reminders, and memory review.\n"
        "- Do not invent tasks, deadlines, life status, prayer status, habit streaks, job results, or personal facts that are absent from the packet.\n"
        "- Treat `today.now` and `today.timezone` as current local time. Do not recommend morning, early-afternoon, or other already-past time blocks.\n"
        "- When giving a plan for today, start from what remains after `today.now`, not a generic full-day schedule.\n"
        "- Normal chat may propose LifeOS mutations as pending actions, but must not claim they are logged, updated, completed, scheduled, or saved until the backend executed the action.\n"
        "- If the user reports a meal, water, task completion, or status update in normal chat and no mutation was executed, propose the log or ask for confirmation instead of pretending it is saved.\n"
        "- If the packet lacks a fact needed for a good answer, say what is missing and ask one concise clarification.\n"
        "- If shared memory is unavailable, use the Today/status packet only and say durable memory context is missing when it matters.\n"
        "--- END LIFEOS STATE PACKET ---\n"
    )
