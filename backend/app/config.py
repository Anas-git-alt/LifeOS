"""LifeOS configuration and runtime path contract."""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


DEFAULT_WORKSPACE_REPO_ROOT = "/workspace"
DEFAULT_DATA_ROOT = "/app/data"
DEFAULT_LEGACY_STORAGE_ROOT = "/app/storage"
REPO_ROOT = Path(__file__).resolve().parents[2]


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
    database_url: str = ""
    api_secret_key: str = "change_me"
    memory_retention_days: int = 60
    audit_retention_days: int = 90
    memory_backend: str = "openviking"
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "06:00"
    nudge_mode: str = "moderate"
    workspace_repo_root: str = DEFAULT_WORKSPACE_REPO_ROOT
    workspace_archive_root: str = ""
    data_root: str = DEFAULT_DATA_ROOT
    legacy_storage_root: str = DEFAULT_LEGACY_STORAGE_ROOT
    obsidian_vault_root: str = ""
    obsidian_index_enabled: bool = True
    obsidian_private_namespaces_enabled: bool = True
    discord_audit_channel: str = ""
    tts_worker_url: str = "http://tts-worker:8010"
    tts_request_timeout_seconds: float = 45.0
    tts_health_timeout_seconds: float = 5.0
    tts_default_engine: str = "chatterbox_turbo"
    tts_default_model_id: str = "chatterbox-turbo"
    tts_enable_cache: bool = True
    tts_cache_ttl_seconds: int = 300

    # Feature flags
    agency_agents_enabled: bool = False
    memory_summarisation_enabled: bool = True
    memory_summarisation_threshold: int = 30

    # GitHub
    github_token: str = ""
    github_repo: str = ""

    # OpenViking
    openviking_enabled: bool = True
    openviking_base_url: str = "http://openviking:1933"
    openviking_api_key: str = ""
    openviking_account: str = "lifeos"
    openviking_user: str = "default"
    openviking_sync_on_startup: bool = True

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

    @property
    def normalized_memory_backend(self) -> str:
        backend = (self.memory_backend or "sqlite").strip().lower()
        return backend if backend in {"sqlite", "openviking"} else "sqlite"

    @staticmethod
    def _resolve_path(raw: str, *, fallback: Path | None = None) -> Path:
        value = str(raw or "").strip()
        candidate = Path(value) if value else fallback
        if candidate is None:
            raise ValueError("Path fallback is required when no explicit value is set")
        return candidate.resolve(strict=False)

    @staticmethod
    def _default_path(raw: str, *, container_path: str, repo_relative: str) -> Path:
        value = str(raw or "").strip()
        if value and value != container_path:
            return Path(value).resolve(strict=False)
        container_candidate = Path(container_path)
        if container_candidate.parent.exists():
            return container_candidate.resolve(strict=False)
        return (REPO_ROOT / repo_relative).resolve(strict=False)

    @staticmethod
    def _path_has_entries(path: Path) -> bool:
        try:
            return any(path.iterdir())
        except FileNotFoundError:
            return False

    @staticmethod
    def _sqlite_path_from_url(url: str) -> str:
        if url.startswith("sqlite+aiosqlite:///"):
            return url.replace("sqlite+aiosqlite:///", "", 1)
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "", 1)
        return ""

    @staticmethod
    def _sqlite_url_from_path(path: Path) -> str:
        return f"sqlite+aiosqlite:///{path.as_posix()}"

    @property
    def workspace_repo_root_path(self) -> Path:
        return self._default_path(
            self.workspace_repo_root,
            container_path=DEFAULT_WORKSPACE_REPO_ROOT,
            repo_relative="",
        )

    @property
    def data_root_path(self) -> Path:
        return self._default_path(
            self.data_root,
            container_path=DEFAULT_DATA_ROOT,
            repo_relative="data",
        )

    @property
    def legacy_storage_root_path(self) -> Path:
        return self._default_path(
            self.legacy_storage_root,
            container_path=DEFAULT_LEGACY_STORAGE_ROOT,
            repo_relative="storage",
        )

    @property
    def canonical_database_path(self) -> Path:
        return self.data_root_path / "sqlite" / "lifeos.db"

    @property
    def legacy_database_path(self) -> Path:
        return self.legacy_storage_root_path / "lifeos.db"

    @property
    def database_path(self) -> Path:
        explicit = (self.database_url or "").strip()
        if explicit:
            sqlite_path = self._sqlite_path_from_url(explicit)
            if sqlite_path:
                return Path(sqlite_path).resolve(strict=False)
        legacy = self.legacy_database_path
        canonical = self.canonical_database_path
        if legacy.exists() and not canonical.exists():
            return legacy
        return canonical

    @property
    def resolved_database_url(self) -> str:
        explicit = (self.database_url or "").strip()
        if explicit:
            return explicit
        return self._sqlite_url_from_path(self.database_path)

    @property
    def canonical_workspace_archive_root_path(self) -> Path:
        return self.data_root_path / "workspace" / "archives"

    @property
    def legacy_workspace_archive_root_path(self) -> Path:
        return self.legacy_storage_root_path / "workspace-archive"

    @property
    def workspace_archive_root_path(self) -> Path:
        explicit = (self.workspace_archive_root or "").strip()
        if explicit:
            return self._resolve_path(explicit)
        legacy = self.legacy_workspace_archive_root_path
        canonical = self.canonical_workspace_archive_root_path
        if legacy.exists() and not self._path_has_entries(canonical):
            return legacy
        return canonical

    @property
    def data_manifest_path(self) -> Path:
        return self.data_root_path / "manifest.json"

    @property
    def obsidian_vault_root_path(self) -> Path | None:
        value = (self.obsidian_vault_root or "").strip()
        if not value:
            return None
        return Path(value).resolve(strict=False)

    @property
    def shared_memory_root_path(self) -> Path:
        vault_root = self.obsidian_vault_root_path
        if vault_root is not None:
            return (vault_root / "shared").resolve(strict=False)
        return (self.data_root_path / "shared").resolve(strict=False)

    @property
    def memory_router_version(self) -> int:
        return 1

    @property
    def data_layout_paths(self) -> list[Path]:
        return [
            self.data_root_path,
            self.data_root_path / "sqlite",
            self.data_root_path / "workspace",
            self.canonical_workspace_archive_root_path,
            self.data_root_path / "exports",
            self.data_root_path / "tmp",
            self.data_root_path / "shared",
            self.data_root_path / "voices",
        ]

    @property
    def effective_openviking_api_key(self) -> str:
        if (self.openviking_api_key or "").strip():
            return self.openviking_api_key.strip()
        fallback = (self.api_secret_key or "").strip()
        if fallback and fallback != "change_me":
            return fallback
        return ""


settings = Settings()
