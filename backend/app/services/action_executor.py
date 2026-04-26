"""Execute approval-gated pending actions."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.database import async_session
from app.models import Agent, AgentCreate, DailyLogCreate, LifeItemCreate, PendingAction, ScheduledJobCreate
from app.services.agent_payloads import build_agent_row
from app.services.jobs import create_job
from app.services.workspace import execute_workspace_delete_action


async def execute_pending_action(action: PendingAction) -> tuple[bool, str]:
    if not action.details:
        return False, "Missing action details"

    try:
        payload = json.loads(action.details)
    except json.JSONDecodeError as exc:
        return False, f"Invalid action details JSON: {exc}"

    if action.action_type == "create_job":
        try:
            from app.services.scheduler import sync_persistent_job

            data = ScheduledJobCreate.model_validate(payload)
            row = await create_job(data)
            await sync_persistent_job(row.id)
            return True, f"Created job #{row.id} ({row.name})"
        except Exception as exc:
            return False, f"Failed creating job: {exc}"

    if action.action_type == "create_agent":
        try:
            from app.services.scheduler import sync_agent_job

            data = AgentCreate.model_validate(payload)
            async with async_session() as db:
                existing = await db.execute(select(Agent).where(Agent.name == data.name))
                if existing.scalar_one_or_none():
                    return False, f"Agent '{data.name}' already exists"
                row = build_agent_row(data)
                db.add(row)
                await db.commit()
                await db.refresh(row)
            if row.enabled and row.cadence:
                await sync_agent_job(
                    agent_name=row.name,
                    cadence=row.cadence,
                    enabled=row.enabled,
                    target_channel=row.discord_channel,
                )
            return True, f"Created agent '{row.name}'"
        except Exception as exc:
            return False, f"Failed creating agent: {exc}"

    if action.action_type == "workspace_delete":
        return await execute_workspace_delete_action(action)

    if action.action_type in {"life_item_create", "task_create"}:
        try:
            from app.services.life import create_life_item
            from app.services.memory_ledger import record_capture_memory

            data = payload.get("details") if isinstance(payload.get("details"), dict) else payload
            if not isinstance(data, dict):
                return False, "Task details must be a JSON object"
            data = dict(data)
            data.setdefault("domain", "planning")
            data.setdefault("kind", "task")
            data.setdefault("priority", "medium")
            data.setdefault("source_agent", action.agent_name)
            item = await create_life_item(LifeItemCreate.model_validate(data))
            try:
                await record_capture_memory(
                    raw_text=(
                        "Agent-created life item.\n"
                        f"Title: {item.title}\n"
                        f"Domain: {item.domain}\n"
                        f"Kind: {item.kind}\n"
                        f"Due: {item.due_at.isoformat() if item.due_at else 'none'}\n"
                        f"Notes: {item.notes or ''}"
                    ),
                    source=action.review_source or "approval",
                    source_agent=action.agent_name,
                    source_session_id=None,
                    life_item=item,
                    event_type="life_item",
                )
            except Exception:
                pass
            due = f" · due {item.due_at.isoformat()}" if item.due_at else ""
            return True, f"Tracked #{item.id}: {item.title}{due}"
        except Exception as exc:
            return False, f"Failed creating task: {exc}"

    if action.action_type == "daily_log_batch":
        from app.services.life import log_daily_signal
        from app.services.memory_ledger import record_daily_log_memory

        logs = payload.get("logs") if isinstance(payload, dict) else None
        if not isinstance(logs, list) or not logs:
            return False, "No daily logs in action details"
        labels: list[str] = []
        try:
            for raw_log in logs:
                data = DailyLogCreate.model_validate(raw_log)
                result = await log_daily_signal(data)
                labels.append(result.get("message") or data.kind)
        except Exception as exc:
            return False, f"Failed logging daily check-in: {exc}"
        result_text = "Logged: " + "; ".join(labels)
        try:
            await record_daily_log_memory(
                raw_logs=logs,
                result_text=result_text,
                source_agent=action.agent_name,
                source=action.review_source or "approval",
            )
        except Exception:
            pass
        return True, result_text

    return False, f"Unsupported action_type '{action.action_type}'"
