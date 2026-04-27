"""Shared-memory routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.database import async_session
from app.models import (
    Agent,
    ContextEventCurateResponse,
    ContextEventResponse,
    JobReplyIntakeRequest,
    JobReplyIntakeResponse,
    MeetingIntakeRequest,
    MeetingIntakeResponse,
    MemoryEvent,
    PrivateMemoryEventResponse,
    SharedMemoryPromoteRequest,
    SharedMemoryPromoteResponse,
    SharedMemoryProposalApplyRequest,
    SharedMemoryProposalResponse,
    SharedMemorySearchResponse,
)
from app.security import require_api_token
from app.services.shared_memory import (
    apply_shared_memory_proposal,
    promote_to_shared_memory,
    search_shared_memory,
)
from app.services.memory_ledger import list_private_memory_events, set_private_memory_event_status
from app.services.context_events import (
    capture_job_reply,
    capture_meeting_summary,
    curate_context_event,
    list_context_events,
)

router = APIRouter()


def _why_saved(row: MemoryEvent) -> str:
    event_type = str(row.event_type or "user_fact")
    if event_type == "user_turn":
        return "Saved from user-authored chat turn for future context."
    if "capture" in event_type:
        return "Saved from capture so future agent turns can recall source details."
    if event_type == "daily_log":
        return "Saved from Today/daily log action for accountability history."
    return "Saved as user-authored private memory."


def _private_memory_response(row: MemoryEvent) -> PrivateMemoryEventResponse:
    return PrivateMemoryEventResponse(
        id=row.id,
        source=row.source,
        source_agent=row.source_agent,
        source_session_id=row.source_session_id,
        source_message=row.raw_text,
        source_uri=row.source_uri,
        scope="private",
        confidence="medium",
        status=row.status,
        event_type=row.event_type,
        domain=row.domain,
        kind=row.kind,
        title=row.title,
        summary=row.summary,
        raw_text=row.raw_text,
        why_saved=_why_saved(row),
        linked_life_item_id=row.linked_life_item_id,
        linked_intake_entry_id=row.linked_intake_entry_id,
        linked_job_id=row.linked_job_id,
        created_at=row.created_at,
    )


async def _load_agent(agent_name: str) -> Agent:
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        return agent


@router.get("/shared/search", response_model=SharedMemorySearchResponse, dependencies=[Depends(require_api_token)])
async def shared_memory_search(
    query: str,
    agent_name: str,
    scope: str | None = None,
    domain: str | None = None,
):
    agent = await _load_agent(agent_name)
    hits = await search_shared_memory(query=query, agent=agent, scope=scope, domain=domain)
    return SharedMemorySearchResponse(query=query, scope=scope, domain=domain, hits=hits)


@router.get(
    "/private/events",
    response_model=list[PrivateMemoryEventResponse],
    dependencies=[Depends(require_api_token)],
)
async def list_private_memory(
    status: str | None = Query(default="active", pattern="^(active|archived|deleted)$"),
    limit: int = Query(default=100, ge=1, le=200),
):
    rows = await list_private_memory_events(status=status, limit=limit)
    return [_private_memory_response(row) for row in rows]


@router.post(
    "/private/events/{event_id}/archive",
    response_model=PrivateMemoryEventResponse,
    dependencies=[Depends(require_api_token)],
)
async def archive_private_memory(event_id: int):
    try:
        row = await set_private_memory_event_status(event_id, "archived")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _private_memory_response(row)


@router.post(
    "/private/events/{event_id}/restore",
    response_model=PrivateMemoryEventResponse,
    dependencies=[Depends(require_api_token)],
)
async def restore_private_memory(event_id: int):
    try:
        row = await set_private_memory_event_status(event_id, "active")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _private_memory_response(row)


@router.post("/promote", response_model=SharedMemoryPromoteResponse, dependencies=[Depends(require_api_token)])
async def promote_shared_memory(data: SharedMemoryPromoteRequest):
    await _load_agent(data.agent_name)
    try:
        result = await promote_to_shared_memory(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SharedMemoryPromoteResponse(**result)


@router.post(
    "/intake/meeting",
    response_model=MeetingIntakeResponse,
    dependencies=[Depends(require_api_token)],
)
async def intake_meeting_summary(data: MeetingIntakeRequest):
    try:
        event, proposals, intake_entry_ids = await capture_meeting_summary(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MeetingIntakeResponse(
        event=ContextEventResponse.model_validate(event),
        proposals=[SharedMemoryProposalResponse.model_validate(row) for row in proposals],
        intake_entry_ids=intake_entry_ids,
    )


@router.get("/events", response_model=list[ContextEventResponse], dependencies=[Depends(require_api_token)])
async def get_memory_events(
    event_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    rows = await list_context_events(event_type=event_type, status=status, limit=limit)
    return [ContextEventResponse.model_validate(row) for row in rows]


@router.post(
    "/events/{event_id}/curate",
    response_model=ContextEventCurateResponse,
    dependencies=[Depends(require_api_token)],
)
async def curate_memory_event(event_id: int):
    try:
        event, proposals, intake_entry_ids = await curate_context_event(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ContextEventCurateResponse(
        event=ContextEventResponse.model_validate(event),
        proposals=[SharedMemoryProposalResponse.model_validate(row) for row in proposals],
        intake_entry_ids=intake_entry_ids,
    )


@router.post(
    "/intake/job-reply",
    response_model=JobReplyIntakeResponse,
    dependencies=[Depends(require_api_token)],
)
async def intake_job_reply(data: JobReplyIntakeRequest):
    try:
        event, run, checkin_id, checkin_result, proposals = await capture_job_reply(data)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "No job notification" in str(exc) else 400, detail=str(exc)) from exc
    return JobReplyIntakeResponse(
        event=ContextEventResponse.model_validate(event),
        job_id=run.job_id,
        job_run_id=run.id,
        life_checkin_id=checkin_id,
        life_checkin_result=checkin_result,
        proposals=[SharedMemoryProposalResponse.model_validate(row) for row in proposals],
    )


@router.post(
    "/proposals/{proposal_id}/apply",
    response_model=SharedMemoryPromoteResponse,
    dependencies=[Depends(require_api_token)],
)
async def apply_memory_proposal(proposal_id: int, data: SharedMemoryProposalApplyRequest):
    try:
        result = await apply_shared_memory_proposal(proposal_id, source_agent=data.source_agent or "webui")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SharedMemoryPromoteResponse(**result)
