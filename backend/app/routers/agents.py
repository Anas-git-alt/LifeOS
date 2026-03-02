"""Agents router: CRUD, chat, and scheduled execution."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.database import async_session
from app.models import Agent, AgentCreate, AgentResponse, AgentUpdate, ChatRequest, ChatResponse
from app.security import require_api_token
from app.services.orchestrator import handle_message, run_scheduled_agent
from app.services.scheduler import add_agent_job, remove_agent_job

router = APIRouter()


@router.get("/", response_model=list[AgentResponse])
async def list_agents():
    async with async_session() as db:
        result = await db.execute(select(Agent).order_by(Agent.id))
        return [AgentResponse.model_validate(agent) for agent in result.scalars().all()]


@router.get("/{agent_name}", response_model=AgentResponse)
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
            add_agent_job(agent.name, agent.cadence)
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
            add_agent_job(agent.name, agent.cadence)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cadence: {exc}") from exc
    else:
        remove_agent_job(agent.name)
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
    remove_agent_job(agent_name)
    return {"detail": f"Agent '{agent_name}' deleted"}


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_token)])
async def chat_with_agent(data: ChatRequest):
    result = await handle_message(
        agent_name=data.agent_name,
        user_message=data.message,
        approval_policy=data.approval_policy,
    )
    return ChatResponse(
        agent_name=data.agent_name,
        response=result["response"],
        pending_action_id=result.get("pending_action_id"),
        risk_level=result.get("risk_level", "low"),
    )


@router.post(
    "/{agent_name}/run-scheduled",
    dependencies=[Depends(require_api_token)],
)
async def run_agent_scheduled(agent_name: str):
    return await run_scheduled_agent(agent_name)
