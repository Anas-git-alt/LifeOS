"""Agents router: CRUD, chat, and scheduled execution."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.database import async_session
from app.models import (
    ActionStatus,
    Agent,
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
    PendingAction,
    ProposedActionPayload,
)
from app.security import require_api_token
from app.services.events import publish_event
from app.services.chat_sessions import (
    clear_session_context,
    create_session,
    get_session_messages,
    list_sessions,
    rename_session,
)
from app.services.orchestrator import handle_message, run_scheduled_agent
from app.services.scheduler import sync_agent_job, unschedule_agent_jobs

router = APIRouter()


async def _ensure_agent_exists(agent_name: str) -> None:
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")


@router.get("/", response_model=list[AgentResponse], dependencies=[Depends(require_api_token)])
async def list_agents():
    async with async_session() as db:
        result = await db.execute(select(Agent).order_by(Agent.id))
        return [AgentResponse.model_validate(agent) for agent in result.scalars().all()]


@router.get("/{agent_name}", response_model=AgentResponse, dependencies=[Depends(require_api_token)])
async def get_agent(agent_name: str):
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        return AgentResponse.model_validate(agent)


@router.post("/", response_model=AgentResponse, dependencies=[Depends(require_api_token)])
async def create_agent(data: AgentCreate):
    async with async_session() as db:
        existing = await db.execute(select(Agent).where(Agent.name == data.name))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Agent '{data.name}' already exists")
        agent = Agent(**data.model_dump())
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
    if agent.enabled and agent.cadence:
        try:
            await sync_agent_job(
                agent_name=agent.name,
                cadence=agent.cadence,
                enabled=agent.enabled,
                target_channel=agent.discord_channel,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cadence: {exc}") from exc
    return AgentResponse.model_validate(agent)


@router.put("/{agent_name}", response_model=AgentResponse, dependencies=[Depends(require_api_token)])
async def update_agent(agent_name: str, data: AgentUpdate):
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(agent, key, value)
        await db.commit()
        await db.refresh(agent)

    if agent.enabled and agent.cadence:
        try:
            await sync_agent_job(
                agent_name=agent.name,
                cadence=agent.cadence,
                enabled=agent.enabled,
                target_channel=agent.discord_channel,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cadence: {exc}") from exc
    else:
        await unschedule_agent_jobs(agent.name)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_name}", dependencies=[Depends(require_api_token)])
async def delete_agent(agent_name: str):
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        await db.delete(agent)
        await db.commit()
    await unschedule_agent_jobs(agent_name)
    return {"detail": f"Agent '{agent_name}' deleted"}


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_token)])
async def chat_with_agent(data: ChatRequest):
    result = await handle_message(
        agent_name=data.agent_name,
        user_message=data.message,
        approval_policy=data.approval_policy,
        session_id=data.session_id,
        session_enabled=True,
    )
    if result.get("error_code") == "session_not_found":
        raise HTTPException(status_code=404, detail=result["response"])
    return ChatResponse(
        agent_name=data.agent_name,
        response=result["response"],
        pending_action_id=result.get("pending_action_id"),
        risk_level=result.get("risk_level", "low"),
        session_id=result.get("session_id"),
        session_title=result.get("session_title"),
    )


@router.get(
    "/{agent_name}/sessions",
    response_model=list[ChatSessionResponse],
    dependencies=[Depends(require_api_token)],
)
async def list_agent_sessions(agent_name: str):
    await _ensure_agent_exists(agent_name)
    sessions = await list_sessions(agent_name)
    return [ChatSessionResponse.model_validate(session) for session in sessions]


@router.post(
    "/{agent_name}/sessions",
    response_model=ChatSessionResponse,
    dependencies=[Depends(require_api_token)],
)
async def create_agent_session(agent_name: str, data: ChatSessionCreate):
    await _ensure_agent_exists(agent_name)
    session = await create_session(agent_name=agent_name, title=data.title)
    return ChatSessionResponse.model_validate(session)


@router.put(
    "/{agent_name}/sessions/{session_id}",
    response_model=ChatSessionResponse,
    dependencies=[Depends(require_api_token)],
)
async def update_agent_session(agent_name: str, session_id: int, data: ChatSessionUpdate):
    await _ensure_agent_exists(agent_name)
    try:
        session = await rename_session(agent_name=agent_name, session_id=session_id, title=data.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChatSessionResponse.model_validate(session)


@router.post(
    "/{agent_name}/sessions/{session_id}/clear",
    response_model=ChatSessionResponse,
    dependencies=[Depends(require_api_token)],
)
async def clear_agent_session(agent_name: str, session_id: int):
    await _ensure_agent_exists(agent_name)
    try:
        session = await clear_session_context(agent_name=agent_name, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChatSessionResponse.model_validate(session)


@router.get(
    "/{agent_name}/sessions/{session_id}/messages",
    response_model=list[ChatMessageResponse],
    dependencies=[Depends(require_api_token)],
)
async def list_agent_session_messages(agent_name: str, session_id: int, limit: int = 200):
    await _ensure_agent_exists(agent_name)
    try:
        messages = await get_session_messages(agent_name=agent_name, session_id=session_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [ChatMessageResponse.model_validate(message) for message in messages]


@router.post(
    "/{agent_name}/run-scheduled",
    dependencies=[Depends(require_api_token)],
)
async def run_agent_scheduled(agent_name: str):
    return await run_scheduled_agent(agent_name)


@router.post("/propose", dependencies=[Depends(require_api_token)])
async def propose_agent(data: ProposedActionPayload):
    async with async_session() as db:
        pending = PendingAction(
            agent_name="agent-factory",
            action_type="create_agent",
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
