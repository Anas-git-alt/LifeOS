"""Obsidian vault routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models import SharedMemoryProposalResponse
from app.security import require_api_token
from app.services.shared_memory import bootstrap_and_sync_vault, list_shared_memory_proposals

router = APIRouter()


@router.post("/sync", dependencies=[Depends(require_api_token)])
async def sync_vault():
    return await bootstrap_and_sync_vault()


@router.get("/conflicts", response_model=list[SharedMemoryProposalResponse], dependencies=[Depends(require_api_token)])
async def list_vault_conflicts():
    rows = await list_shared_memory_proposals(status="pending")
    return [SharedMemoryProposalResponse.model_validate(row) for row in rows]
