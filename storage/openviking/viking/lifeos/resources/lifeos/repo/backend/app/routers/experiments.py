"""Router for experiment runs — shadow test results and promotion requests."""

import logging

from fastapi import APIRouter, Depends, Query

from app.services.experiment_log import get_experiments
from app.services.telemetry import get_provider_stats
from app.security import require_api_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.get("", dependencies=[Depends(require_api_token)])
async def list_experiments(limit: int = Query(default=50, ge=1, le=500)):
    """Return recent shadow-router experiment runs."""
    runs = await get_experiments(limit=limit)
    return {"experiments": runs, "total": len(runs)}


@router.get("/telemetry", dependencies=[Depends(require_api_token)])
async def provider_telemetry():
    """Return live in-memory provider telemetry stats."""
    stats = get_provider_stats()
    return {"providers": stats}
