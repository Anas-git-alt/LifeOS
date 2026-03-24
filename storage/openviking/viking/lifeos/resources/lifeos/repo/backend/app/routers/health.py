"""Health and readiness router."""

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import async_session
from app.services.openviking_client import OpenVikingUnavailableError, openviking_client
from app.services.runtime_state import (
    OPENVIKING_MEMORY_IMPORT_STATE_KEY,
    OPENVIKING_WORKSPACE_SYNC_STATE_KEY,
    get_runtime_state_value,
)

router = APIRouter()


@router.get("/health")
async def health_check():
    openviking_ok = False
    openviking_payload: dict | None = None
    openviking_error: str | None = None
    try:
        openviking_payload = await openviking_client.health()
        openviking_ok = bool(openviking_payload.get("healthy"))
    except Exception as exc:
        openviking_error = str(exc)
    status = "healthy" if openviking_ok else "degraded"
    return {
        "status": status,
        "service": "lifeos-backend",
        "version": "1-5",
        "memory_backend": settings.normalized_memory_backend,
        "openviking_enabled": settings.openviking_enabled,
        "openviking": {
            "healthy": openviking_ok,
            "payload": openviking_payload,
            "error": openviking_error,
        },
    }


@router.get("/readiness")
async def readiness_check():
    db_ok = False
    openviking_ok = False
    openviking_error: str | None = None
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False

    try:
        await openviking_client.validate_ready()
        openviking_ok = True
    except OpenVikingUnavailableError as exc:
        openviking_error = str(exc)
    except Exception as exc:  # pragma: no cover - defensive fallback
        openviking_error = str(exc)

    import_state = None
    sync_state = None
    if db_ok:
        import_state = await get_runtime_state_value(OPENVIKING_MEMORY_IMPORT_STATE_KEY)
        sync_state = await get_runtime_state_value(OPENVIKING_WORKSPACE_SYNC_STATE_KEY)
    return {
        "status": "ready" if db_ok and openviking_ok else "degraded",
        "database": db_ok,
        "openviking": {
            "ready": openviking_ok,
            "error": openviking_error,
        },
        "memory_import_state": import_state,
        "workspace_sync_state": sync_state,
    }
