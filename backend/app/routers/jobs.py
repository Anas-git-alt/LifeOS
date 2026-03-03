"""Scheduled jobs management router."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import async_session
from app.models import (
    ActionStatus,
    JobRunLogResponse,
    PendingAction,
    ProposedActionPayload,
    ScheduledJobCreate,
    ScheduledJobResponse,
    ScheduledJobUpdate,
)
from app.security import require_api_token
from app.services.events import publish_event
from app.services.jobs import (
    create_job,
    delete_job,
    get_job,
    list_job_run_logs,
    list_jobs,
    pause_job,
    resume_job,
    update_job,
)
from app.services.scheduler import scheduler, sync_persistent_job

router = APIRouter()


def _scheduler_next_run(job_id: int):
    live = scheduler.get_job(f"scheduled_job_{job_id}")
    return live.next_run_time if live else None


def _to_response(row) -> ScheduledJobResponse:
    next_run = _scheduler_next_run(row.id)
    return ScheduledJobResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        agent_name=row.agent_name,
        job_type=row.job_type,
        cron_expression=row.cron_expression,
        timezone=row.timezone,
        target_channel=row.target_channel,
        prompt_template=row.prompt_template,
        enabled=row.enabled,
        paused=row.paused,
        approval_required=row.approval_required,
        source=row.source,
        created_by=row.created_by,
        config_json=row.config_json,
        last_run_at=row.last_run_at,
        next_run_at=next_run or row.next_run_at,
        last_status=row.last_status,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/", response_model=list[ScheduledJobResponse], dependencies=[Depends(require_api_token)])
async def get_jobs(agent_name: Optional[str] = Query(default=None)):
    rows = await list_jobs(agent_name=agent_name)
    return [_to_response(row) for row in rows]


@router.post("/propose", dependencies=[Depends(require_api_token)])
async def propose_job_action(data: ProposedActionPayload):
    async with async_session() as db:
        pending = PendingAction(
            agent_name="scheduler",
            action_type="create_job",
            summary=data.summary,
            details=json.dumps(data.details),
            status=ActionStatus.PENDING,
            risk_level="medium",
            reviewed_by=None,
            review_source=data.source,
        )
        db.add(pending)
        await db.commit()
        await db.refresh(pending)
        await publish_event(
            "approvals.pending.updated",
            {"kind": "approval", "id": str(pending.id)},
            {"action_id": pending.id, "status": pending.status.value, "agent_name": pending.agent_name},
        )
        return {"pending_action_id": pending.id, "status": pending.status.value}


@router.get("/{job_id}", response_model=ScheduledJobResponse, dependencies=[Depends(require_api_token)])
async def get_job_by_id(job_id: int):
    row = await get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(row)


@router.post("/", response_model=ScheduledJobResponse, dependencies=[Depends(require_api_token)])
async def post_job(data: ScheduledJobCreate):
    row = await create_job(data)
    await sync_persistent_job(row.id)
    refreshed = await get_job(row.id)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Created job was not found")
    return _to_response(refreshed)


@router.put("/{job_id}", response_model=ScheduledJobResponse, dependencies=[Depends(require_api_token)])
async def put_job(job_id: int, data: ScheduledJobUpdate):
    row = await update_job(job_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    await sync_persistent_job(job_id)
    refreshed = await get_job(job_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(refreshed)


@router.post("/{job_id}/pause", response_model=ScheduledJobResponse, dependencies=[Depends(require_api_token)])
async def post_pause_job(job_id: int):
    row = await pause_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    await sync_persistent_job(job_id)
    refreshed = await get_job(job_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(refreshed)


@router.post("/{job_id}/resume", response_model=ScheduledJobResponse, dependencies=[Depends(require_api_token)])
async def post_resume_job(job_id: int):
    row = await resume_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    await sync_persistent_job(job_id)
    refreshed = await get_job(job_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(refreshed)


@router.delete("/{job_id}", dependencies=[Depends(require_api_token)])
async def delete_job_by_id(job_id: int):
    await pause_job(job_id)
    await sync_persistent_job(job_id)
    ok = await delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"detail": "Job deleted"}


@router.get("/{job_id}/runs", response_model=list[JobRunLogResponse], dependencies=[Depends(require_api_token)])
async def get_job_runs(job_id: int, limit: int = Query(default=20, ge=1, le=200)):
    return [JobRunLogResponse.model_validate(row) for row in await list_job_run_logs(job_id, limit=limit)]
