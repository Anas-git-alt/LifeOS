"""Provider and capability router."""

from fastapi import APIRouter

from app.config import settings
from app.services.provider_router import get_available_providers

router = APIRouter()


@router.get("/")
async def list_providers():
    return get_available_providers()


@router.get("/capabilities")
async def list_capabilities():
    return {
        "free_only_mode": {
            "enabled": settings.free_only_mode,
            "reason": "active" if settings.free_only_mode else "disabled",
        },
        "shadow_router": {
            "enabled": settings.shadow_router_enabled,
            "reason": "enabled" if settings.shadow_router_enabled else "disabled_by_default_for_free_quota",
        },
        "web_search": {"enabled": True, "provider": "brave" if settings.brave_api_key else "duckduckgo"},
    }
