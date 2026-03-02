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
        "calendar": {"enabled": False, "reason": "not_configured"},
        "email": {"enabled": False, "reason": "not_configured"},
        "web_search": {"enabled": True, "provider": "brave" if settings.brave_api_key else "duckduckgo"},
    }
