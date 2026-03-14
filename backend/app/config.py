"""LifeOS configuration - loads secrets from .venv/.env."""

from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env from .venv/.env (project root) or fallback to env vars (Docker)
_project_root = Path(__file__).resolve().parent.parent.parent
_env_path = _project_root / ".venv" / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


class Settings(BaseSettings):
    # Discord
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    discord_owner_ids: str = ""

    # LLM Providers
    openrouter_api_key: str = ""
    openrouter_default_model: str = "openrouter/auto"
    nvidia_api_key: str = ""
    nvidia_default_model: str = "meta/llama-3.1-8b-instruct"
    google_api_key: str = ""
    google_default_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_default_model: str = "gpt-4o-mini"
    default_provider: str = "openrouter"

    # Tools
    brave_api_key: str = ""

    # Prayer
    prayer_city: str = "Casablanca"
    prayer_country: str = "Morocco"
    prayer_method: int = 2

    # General
    timezone: str = "Africa/Casablanca"
    local_mode: bool = True
    cors_allow_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100"
    )
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///storage/lifeos.db"
    api_secret_key: str = "change_me"
    memory_retention_days: int = 60
    audit_retention_days: int = 90
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "06:00"
    nudge_mode: str = "moderate"
    tts_worker_url: str = "http://tts-worker:8010"
    tts_request_timeout_seconds: float = 45.0
    tts_health_timeout_seconds: float = 5.0
    tts_default_engine: str = "chatterbox_turbo"
    tts_default_model_id: str = "chatterbox-turbo"
    tts_enable_cache: bool = True
    tts_cache_ttl_seconds: int = 300

    # GitHub
    github_token: str = ""
    github_repo: str = ""

    class Config:
        env_file = ".venv/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def cors_origins(self) -> List[str]:
        if not self.cors_allow_origins:
            return []
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def owner_ids(self) -> set[int]:
        owners: set[int] = set()
        for raw in self.discord_owner_ids.split(","):
            raw = raw.strip()
            if raw.isdigit():
                owners.add(int(raw))
        return owners


settings = Settings()
