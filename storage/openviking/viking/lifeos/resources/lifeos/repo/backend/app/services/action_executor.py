"""Execute approval-gated pending actions."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.database import async_session
from app.models import Agent, AgentCreate, PendingAction, ScheduledJobCreate
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

    return False, f"Unsupported action_type '{action.action_type}'"
