"""Workspace archive, restore, and OpenViking sync routes."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from app.models import WorkspaceArchiveEntryResponse
from app.security import require_api_token
from app.services.workspace import list_workspace_archives, restore_workspace_archive, sync_workspace_resources

router = APIRouter()


class WorkspaceRestoreRequest(BaseModel):
    source_agent: str = "webui"


class WorkspaceSyncRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


@router.get("/archives", response_model=list[WorkspaceArchiveEntryResponse], dependencies=[Depends(require_api_token)])
async def get_workspace_archives(agent_name: str | None = None, limit: int = 100):
    rows = await list_workspace_archives(agent_name=agent_name, limit=max(1, min(limit, 500)))
    return [WorkspaceArchiveEntryResponse.model_validate(row) for row in rows]


@router.post(
    "/archives/{archive_entry_id}/restore",
    response_model=WorkspaceArchiveEntryResponse,
    dependencies=[Depends(require_api_token)],
)
async def restore_archive(archive_entry_id: int, data: WorkspaceRestoreRequest):
    try:
        row = await restore_workspace_archive(
            archive_entry_id,
            source_agent=data.source_agent or "webui",
            source="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceArchiveEntryResponse.model_validate(row)


@router.post("/sync", dependencies=[Depends(require_api_token)])
async def sync_workspace(data: WorkspaceSyncRequest | None = None):
    paths = data.paths if data and data.paths else None
    return await sync_workspace_resources(paths=paths)
