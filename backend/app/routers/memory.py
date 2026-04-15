"""Shared-memory routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.database import async_session
from app.models import (
    Agent,
    SharedMemoryPromoteRequest,
    SharedMemoryPromoteResponse,
    SharedMemoryProposalApplyRequest,
    SharedMemorySearchResponse,
)
from app.security import require_api_token
from app.services.shared_memory import (
    apply_shared_memory_proposal,
    promote_to_shared_memory,
    search_shared_memory,
)

router = APIRouter()


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


@router.post("/promote", response_model=SharedMemoryPromoteResponse, dependencies=[Depends(require_api_token)])
async def promote_shared_memory(data: SharedMemoryPromoteRequest):
    await _load_agent(data.agent_name)
    try:
        result = await promote_to_shared_memory(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SharedMemoryPromoteResponse(**result)


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
