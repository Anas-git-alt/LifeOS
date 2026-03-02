"""LifeOS FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.middleware import request_context_middleware
from app.routers import agents, approvals, health, life, prayer, profile, providers
from app.services.scheduler import bootstrap_agent_jobs, shutdown_scheduler, start_scheduler
from app.services.seed import seed_default_agents

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("lifeos.backend")


def _startup_self_check():
    warnings: list[str] = []
    if settings.api_secret_key == "change_me":
        warnings.append("API_SECRET_KEY is default; set a strong value for production")
    if not any(
        [
            settings.openrouter_api_key,
            settings.nvidia_api_key,
            settings.google_api_key,
            settings.openai_api_key,
        ]
    ):
        warnings.append("No LLM API keys configured")
    for warning in warnings:
        logger.warning("startup_check: %s", warning)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_default_agents()
    _startup_self_check()
    start_scheduler()
    await bootstrap_agent_jobs()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="LifeOS",
    description="Self-hosted AI agent system for life organizing",
    version="0.2.0",
    lifespan=lifespan,
)

allowed_origins = settings.cors_origins if settings.local_mode else ["*"]
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
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(approvals.router, prefix="/api/approvals", tags=["approvals"])
app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(life.router, prefix="/api/life", tags=["life"])
app.include_router(prayer.router, prefix="/api/prayer", tags=["prayer"])
