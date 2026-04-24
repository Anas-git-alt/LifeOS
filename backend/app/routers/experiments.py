"""Router for experiment runs — shadow test results and promotion requests."""

import logging

from fastapi import APIRouter, Depends, Query

from app.services.experiment_log import get_experiments, get_pending_promotion_requests
from app.services.telemetry import get_provider_stats
from app.security import require_api_token
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.get("", dependencies=[Depends(require_api_token)])
async def list_experiments(limit: int = Query(default=50, ge=1, le=500)):
    """Return recent shadow-router experiment runs."""
    runs = await get_experiments(limit=limit)
    pending_promotions = await get_pending_promotion_requests()
    return {
        "experiments": runs,
        "total": len(runs),
        "pending_promotions": pending_promotions,
        "shadow_router_enabled": settings.shadow_router_enabled,
        "free_only_mode": settings.free_only_mode,
    }


@router.get("/telemetry", dependencies=[Depends(require_api_token)])
async def provider_telemetry():
    """Return live in-memory provider telemetry stats."""
    stats = get_provider_stats()
    return {
        "providers": stats,
        "shadow_router_enabled": settings.shadow_router_enabled,
        "free_only_mode": settings.free_only_mode,
    }
