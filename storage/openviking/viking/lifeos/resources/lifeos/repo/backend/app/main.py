"""LifeOS FastAPI application."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.middleware import request_context_middleware
from app.routers import (
    agents,
    approvals,
    events,
    experiments,
    health,
    jobs,
    life,
    prayer,
    profile,
    providers,
    settings as system_settings,
    tts,
    voice,
    workspace,
)
from app.services.memory import get_legacy_memory_max_entry_id, import_legacy_memory_to_openviking
from app.services.openviking_client import close_openviking_client, openviking_client
from app.services.provider_router import close_all_clients
from app.services.runtime_state import (
    OPENVIKING_MEMORY_IMPORT_STATE_KEY,
    get_runtime_state_value,
    set_runtime_state,
)
from app.services.scheduler import bootstrap_agent_jobs, shutdown_scheduler, start_scheduler
from app.services.seed import seed_default_agents
from app.services.tts_catalog import sync_tts_registry
from app.services.workspace import sync_workspace_resources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("lifeos.backend")


def _startup_self_check() -> None:
    if settings.api_secret_key == "change_me":
        raise RuntimeError(
            "API_SECRET_KEY is set to the default value 'change_me'. "
            "Generate a strong secret with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set it in your .env file before starting LifeOS."
        )
    if settings.normalized_memory_backend != "openviking" or not settings.openviking_enabled:
        raise RuntimeError(
            "LifeOS is configured for a full OpenViking cutover. "
            "Set MEMORY_BACKEND=openviking and OPENVIKING_ENABLED=true before startup."
        )
    if not settings.effective_openviking_api_key:
        raise RuntimeError(
            "OpenViking requires OPENVIKING_API_KEY or a non-default API_SECRET_KEY before startup."
        )
    if not any(
        [
            settings.openrouter_api_key,
            settings.nvidia_api_key,
            settings.google_api_key,
            settings.openai_api_key,
        ]
    ):
        logger.warning("startup_check: No LLM API keys configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_self_check()
    settings.workspace_archive_root_path.mkdir(parents=True, exist_ok=True)
    await init_db()
    await seed_default_agents()
    await sync_tts_registry()

    health_payload = await openviking_client.validate_ready()
    logger.info("openviking_ready payload=%s", health_payload)

    try:
        max_memory_entry_id = await get_legacy_memory_max_entry_id()
        import_state = await get_runtime_state_value(OPENVIKING_MEMORY_IMPORT_STATE_KEY)
        already_imported = (
            bool(import_state)
            and import_state.get("status") == "completed"
            and int(import_state.get("imported_max_memory_entry_id") or 0) >= max_memory_entry_id
        )
        if already_imported:
            logger.info("openviking_memory_import skipped up_to=%s", max_memory_entry_id)
        else:
            import_result = await import_legacy_memory_to_openviking()
            logger.info("openviking_memory_import result=%s", import_result)
            await set_runtime_state(
                OPENVIKING_MEMORY_IMPORT_STATE_KEY,
                {
                    "status": "completed" if import_result.get("complete") else "partial",
                    "imported_at": datetime.now(timezone.utc).isoformat(),
                    "imported_max_memory_entry_id": int(import_result.get("max_memory_entry_id") or 0),
                    "sessions": int(import_result.get("sessions") or 0),
                    "messages": int(import_result.get("messages") or 0),
                    "summaries": int(import_result.get("summaries") or 0),
                    "skipped_sessions": int(import_result.get("skipped_sessions") or 0),
                },
            )
    except Exception:
        logger.exception("Failed importing legacy SQLite memory into OpenViking")

    if settings.openviking_sync_on_startup:
        try:
            sync_result = await sync_workspace_resources()
            logger.info("openviking_workspace_sync result=%s", sync_result)
        except Exception:
            logger.exception("Failed syncing workspace resources to OpenViking on startup")

    start_scheduler()
    await bootstrap_agent_jobs()
    yield
    shutdown_scheduler()
    await close_all_clients()
    await close_openviking_client()


app = FastAPI(
    title="LifeOS",
    description="Self-hosted AI agent system for life organizing",
    version="1.5.0",
    lifespan=lifespan,
)

# Always use the explicit allowlist; never open to "*".
# LOCAL_MODE only controls whether credentials (cookies) are included.
allowed_origins = settings.cors_origins
allow_credentials = bool(settings.local_mode)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(request_context_middleware)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(approvals.router, prefix="/api/approvals", tags=["approvals"])
app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
app.include_router(voice.router, prefix="/api/voice/sessions", tags=["voice"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(system_settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(life.router, prefix="/api/life", tags=["life"])
app.include_router(prayer.router, prefix="/api/prayer", tags=["prayer"])
app.include_router(workspace.router, prefix="/api/workspace", tags=["workspace"])
app.include_router(experiments.router)
