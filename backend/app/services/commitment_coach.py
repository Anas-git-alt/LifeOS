"""AI-backed commitment coaching helpers."""

from __future__ import annotations

import json
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import async_session
from app.models import Agent, AuditLog, DailyScorecard, IntakeEntry, LifeCheckin, LifeItem, UserProfile
from app.services.life import get_today_agenda
from app.services.provider_router import LLMProvidersExhaustedError, chat_completion

DEFAULT_TIMEZONE = "Africa/Casablanca"
COACH_LLM_TIMEOUT_SECONDS = 8.0


def _clean_json_response(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


async def _get_coach_agent() -> Agent | None:
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == "commitment-coach"))
        return result.scalar_one_or_none()


def _agent_temperature(agent: Agent | None) -> float:
    raw = (agent.config_json or {}).get("temperature", 0.2) if agent else 0.2
    try:
        return max(0.0, min(float(raw), 1.0))
    except (TypeError, ValueError):
        return 0.2


def _agent_max_tokens(agent: Agent | None) -> int:
    raw = (agent.config_json or {}).get("max_tokens", 900) if agent else 900
    try:
        return max(256, min(int(raw), 2000))
    except (TypeError, ValueError):
        return 900


async def _coach_chat_completion(
    messages: list[dict],
    *,
    agent: Agent,
    max_tokens_cap: int,
) -> str:
    return await asyncio.wait_for(
        chat_completion(
            messages,
            provider=agent.provider,
            model=agent.model,
            fallback_provider=agent.fallback_provider,
            fallback_model=agent.fallback_model,
            temperature=_agent_temperature(agent),
            max_tokens=min(_agent_max_tokens(agent), max_tokens_cap),
        ),
        timeout=COACH_LLM_TIMEOUT_SECONDS,
    )


def _fallback_daily_focus(agenda: dict) -> dict:
    shortlist = list(agenda.get("top_focus") or [])
    if not shortlist:
        return {
            "primary_item_id": None,
            "why_now": "No ranked commitments yet. Capture one thing you said you would do.",
            "first_step": "Use `!commit ...` or add one life item with a real deadline.",
            "defer_ids": [],
            "nudge_copy": "No commitment radar item yet. Capture one promise before opening new loops.",
            "fallback_used": True,
        }
    primary = shortlist[0]
    defer_ids = [item["id"] for item in shortlist[1:3]]
    reason = primary.get("focus_reason") or "This is the top-ranked open commitment right now."
    return {
        "primary_item_id": primary["id"],
        "why_now": reason,
        "first_step": f"Do the smallest visible next step on '{primary['title']}' now.",
        "defer_ids": defer_ids,
        "nudge_copy": f"Before opening anything new, move '{primary['title']}' one visible step forward.",
        "fallback_used": True,
    }


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def get_daily_focus_coach() -> dict:
    agenda = await get_today_agenda()
    shortlist = list(agenda.get("top_focus") or [])[:3]
    fallback = _fallback_daily_focus(agenda)
    if not shortlist:
        return fallback

    agent = await _get_coach_agent()
    if not agent:
        return fallback

    allowed_ids = [item["id"] for item in shortlist]
    prompt = {
        "mode": "daily_focus_json",
        "timezone": agenda.get("timezone", DEFAULT_TIMEZONE),
        "now": str(agenda.get("now")),
        "rescue_plan": agenda.get("rescue_plan") or {},
        "scorecard": agenda.get("scorecard") or {},
        "next_prayer": agenda.get("next_prayer") or {},
        "inbox_ready_count": int((agenda.get("intake_summary") or {}).get("ready", 0)),
        "shortlist": [
            {
                "id": item["id"],
                "title": item["title"],
                "domain": item.get("domain"),
                "priority": item.get("priority"),
                "focus_reason": item.get("focus_reason"),
                "follow_up_due_at": item.get("follow_up_due_at"),
                "due_at": item.get("due_at"),
            }
            for item in shortlist
        ],
    }
    messages = [
        {"role": "system", "content": agent.system_prompt},
        {
            "role": "user",
            "content": (
                "Return JSON only. Allowed item ids are strictly these ids.\n"
                "Schema:\n"
                '{"primary_item_id": 1, "why_now": "...", "first_step": "...", "defer_ids": [2], "nudge_copy": "..."}'
                "\nInput:\n"
                f"{json.dumps(prompt, default=str)}"
            ),
        },
    ]
    try:
        response = await _coach_chat_completion(
            messages,
            agent=agent,
            max_tokens_cap=500,
        )
        parsed = json.loads(_clean_json_response(response))
        primary_item_id = parsed.get("primary_item_id")
        if primary_item_id not in allowed_ids:
            raise ValueError("primary_item_id outside shortlist")
        defer_ids = [item_id for item_id in parsed.get("defer_ids") or [] if item_id in allowed_ids and item_id != primary_item_id]
        return {
            "primary_item_id": primary_item_id,
            "why_now": str(parsed.get("why_now") or fallback["why_now"]).strip(),
            "first_step": str(parsed.get("first_step") or fallback["first_step"]).strip(),
            "defer_ids": defer_ids,
            "nudge_copy": str(parsed.get("nudge_copy") or fallback["nudge_copy"]).strip(),
            "fallback_used": False,
        }
    except (json.JSONDecodeError, ValueError, KeyError, LLMProvidersExhaustedError, asyncio.TimeoutError):
        return fallback
    except Exception:
        return fallback


def _resolve_profile_tz(profile: UserProfile | None) -> ZoneInfo:
    try:
        return ZoneInfo(profile.timezone if profile else DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def _fallback_weekly_review(summary: dict) -> dict:
    completed = summary["completed_count"]
    missed = summary["missed_count"]
    snoozed = summary["snoozed_count"]
    reopened = summary["reopened_count"]
    stale = summary["stale_titles"]
    backlog = summary["inbox_backlog_titles"]

    wins = [
        f"Closed {completed} commitment{'s' if completed != 1 else ''} this week.",
        f"Logged scorecards on {summary['scorecard_days']} day{'s' if summary['scorecard_days'] != 1 else ''} this week.",
    ]
    if not backlog:
        wins.append("Inbox backlog stayed under control.")

    repeat_blockers = []
    if snoozed:
        repeat_blockers.append(f"Snoozed commitments {snoozed} time{'s' if snoozed != 1 else ''}.")
    if reopened:
        repeat_blockers.append(f"Reopened commitments {reopened} time{'s' if reopened != 1 else ''}.")
    if missed:
        repeat_blockers.append(f"Missed {missed} commitment{'s' if missed != 1 else ''}.")
    if not repeat_blockers:
        repeat_blockers.append("No repeat blocker pattern strong enough to flag yet.")

    stale_commitments = stale or ["No stale commitments detected right now."]
    promises_at_risk = summary["at_risk_titles"] or ["No promise looks actively at risk right now."]
    simplify_next_week = [
        "Keep only 3 active commitments with real deadlines at one time.",
        "Convert vague promises into one visible next step the same day you capture them.",
    ]
    if backlog:
        simplify_next_week.append("Clear or park inbox backlog before adding new commitments.")

    return {
        "wins": wins[:5],
        "stale_commitments": stale_commitments[:5],
        "repeat_blockers": repeat_blockers[:5],
        "promises_at_risk": promises_at_risk[:5],
        "simplify_next_week": simplify_next_week[:5],
        "fallback_used": True,
    }


async def get_weekly_commitment_review() -> dict:
    async with async_session() as db:
        profile_result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = profile_result.scalar_one_or_none()
        tz = _resolve_profile_tz(profile)
        now_local = datetime.now(timezone.utc).astimezone(tz)
        start_local_date = now_local.date() - timedelta(days=6)
        start_utc = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_utc - timedelta(days=6)
        start_utc = start_utc.astimezone(timezone.utc).replace(tzinfo=None)

        scorecards_result = await db.execute(
            select(DailyScorecard)
            .where(DailyScorecard.local_date >= start_local_date)
            .where(DailyScorecard.local_date <= now_local.date())
            .order_by(DailyScorecard.local_date.asc())
        )
        scorecards = list(scorecards_result.scalars().all())

        commitments_result = await db.execute(
            select(LifeItem)
            .where(LifeItem.follow_up_job_id.is_not(None))
            .order_by(LifeItem.updated_at.desc(), LifeItem.id.desc())
        )
        commitments = list(commitments_result.scalars().all())

        checkins_result = await db.execute(
            select(LifeCheckin, LifeItem)
            .join(LifeItem, LifeItem.id == LifeCheckin.life_item_id)
            .where(LifeItem.follow_up_job_id.is_not(None))
            .where(LifeCheckin.timestamp >= start_utc)
            .order_by(LifeCheckin.timestamp.desc())
        )
        checkins = list(checkins_result.all())

        audit_result = await db.execute(
            select(AuditLog)
            .where(AuditLog.agent_name == "commitment-loop")
            .where(AuditLog.timestamp >= start_utc)
            .order_by(AuditLog.timestamp.desc())
        )
        audits = list(audit_result.scalars().all())

        inbox_result = await db.execute(
            select(IntakeEntry)
            .where(IntakeEntry.status.in_(["ready", "clarifying"]))
            .where(IntakeEntry.linked_life_item_id.is_(None))
            .order_by(IntakeEntry.updated_at.desc(), IntakeEntry.id.desc())
        )
        inbox_backlog = list(inbox_result.scalars().all())

    now_utc = datetime.now(timezone.utc)
    stale_titles = [
        item.title
        for item in commitments
        if item.status == "open"
        and (
            (_as_aware_utc(item.due_at) is not None and _as_aware_utc(item.due_at) < now_utc)
            or (_as_aware_utc(item.updated_at) is not None and _as_aware_utc(item.updated_at) <= now_utc - timedelta(days=7))
        )
    ][:5]
    at_risk_titles = [
        item.title
        for item in commitments
        if item.status == "open"
        and item.priority == "high"
        and (
            _as_aware_utc(item.due_at) is not None
            or (_as_aware_utc(item.updated_at) is not None and _as_aware_utc(item.updated_at) <= now_utc - timedelta(days=3))
        )
    ][:5]

    summary = {
        "timezone": getattr(profile, "timezone", DEFAULT_TIMEZONE),
        "scorecard_days": len(scorecards),
        "completed_count": sum(1 for checkin, _ in checkins if checkin.result == "done"),
        "missed_count": sum(1 for checkin, _ in checkins if checkin.result == "missed"),
        "reopened_count": sum(1 for audit in audits if audit.action == "life_item_reopened"),
        "snoozed_count": sum(1 for audit in audits if audit.action == "life_item_snoozed"),
        "stale_titles": stale_titles,
        "at_risk_titles": at_risk_titles,
        "inbox_backlog_titles": [entry.title or entry.raw_text[:80] for entry in inbox_backlog[:5]],
    }
    fallback = _fallback_weekly_review(summary)

    agent = await _get_coach_agent()
    if not agent:
        return fallback

    prompt = {
        "mode": "weekly_review_json",
        "window_days": 7,
        "summary": summary,
        "recent_scorecards": [
            {
                "local_date": str(scorecard.local_date),
                "sleep_hours": scorecard.sleep_hours,
                "meals_count": scorecard.meals_count,
                "hydration_count": scorecard.hydration_count,
                "training_status": scorecard.training_status,
                "priority_done": scorecard.top_priority_completed_count,
                "shutdown_done": scorecard.shutdown_done,
                "rescue_status": scorecard.rescue_status,
            }
            for scorecard in scorecards
        ],
        "recent_checkins": [
            {
                "title": item.title,
                "result": checkin.result,
                "timestamp": str(checkin.timestamp),
            }
            for checkin, item in checkins[:12]
        ],
    }
    messages = [
        {"role": "system", "content": agent.system_prompt},
        {
            "role": "user",
            "content": (
                "Return JSON only.\n"
                "Schema:\n"
                '{"wins":["..."],"stale_commitments":["..."],"repeat_blockers":["..."],"promises_at_risk":["..."],"simplify_next_week":["..."]}'
                "\nInput:\n"
                f"{json.dumps(prompt, default=str)}"
            ),
        },
    ]
    try:
        response = await _coach_chat_completion(
            messages,
            agent=agent,
            max_tokens_cap=700,
        )
        parsed = json.loads(_clean_json_response(response))
        return {
            "wins": [str(item).strip() for item in parsed.get("wins") or [] if str(item).strip()][:5] or fallback["wins"],
            "stale_commitments": [str(item).strip() for item in parsed.get("stale_commitments") or [] if str(item).strip()][:5] or fallback["stale_commitments"],
            "repeat_blockers": [str(item).strip() for item in parsed.get("repeat_blockers") or [] if str(item).strip()][:5] or fallback["repeat_blockers"],
            "promises_at_risk": [str(item).strip() for item in parsed.get("promises_at_risk") or [] if str(item).strip()][:5] or fallback["promises_at_risk"],
            "simplify_next_week": [str(item).strip() for item in parsed.get("simplify_next_week") or [] if str(item).strip()][:5] or fallback["simplify_next_week"],
            "fallback_used": False,
        }
    except (json.JSONDecodeError, KeyError, ValueError, LLMProvidersExhaustedError, asyncio.TimeoutError):
        return fallback
    except Exception:
        return fallback
