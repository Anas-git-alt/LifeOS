"""LifeOS FastAPI application."""

import logging
from contextlib import asynccontextmanager

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
)
from app.services.scheduler import bootstrap_agent_jobs, shutdown_scheduler, start_scheduler
from app.services.seed import seed_default_agents
from app.services.tts_catalog import sync_tts_registry
from app.services.provider_router import close_all_clients

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("lifeos.backend")


def _startup_self_check():
    # Hard-fail on default secret key — a log warning is not a security gate.
    if settings.api_secret_key == "change_me":
        raise RuntimeError(
            "API_SECRET_KEY is set to the default value 'change_me'. "
            "Generate a strong secret with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set it in your .env file before starting LifeOS."
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
    await init_db()
    await seed_default_agents()
    await sync_tts_registry()
    _startup_self_check()
    start_scheduler()
    await bootstrap_agent_jobs()
    yield
    shutdown_scheduler()
    await close_all_clients()


app = FastAPI(
    title="LifeOS",
    description="Self-hosted AI agent system for life organizing",
    version="1.5.0",
    lifespan=lifespan,
)

# Always use the explicit allowlist — never open to "*".
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
app.include_router(experiments.router)
