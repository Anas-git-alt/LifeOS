from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
TEST_RUNTIME_DIR = REPO_ROOT / "tmp" / "backend-pytest"
TEST_DB_PATH = TEST_RUNTIME_DIR / "lifeos-test.db"
TEST_ARCHIVE_DIR = TEST_RUNTIME_DIR / "workspace-archive"

os.environ["API_SECRET_KEY"] = "pytest-secret-key"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["WORKSPACE_REPO_ROOT"] = str(REPO_ROOT)
os.environ["WORKSPACE_ARCHIVE_ROOT"] = str(TEST_ARCHIVE_DIR)
os.environ["OPENVIKING_ENABLED"] = "true"
os.environ["MEMORY_BACKEND"] = "openviking"
os.environ["OPENVIKING_API_KEY"] = "pytest-openviking-key"
os.environ["OPENVIKING_BASE_URL"] = "http://127.0.0.1:1933"
os.environ["OPENVIKING_SYNC_ON_STARTUP"] = "false"
os.environ["DISCORD_OWNER_IDS"] = "1"


@pytest.fixture(autouse=True)
def _stub_app_lifespan_dependencies(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.main.sync_tts_registry", AsyncMock(return_value=None))
    monkeypatch.setattr("app.main.seed_default_agents", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.main.openviking_client.validate_ready",
        AsyncMock(return_value={"healthy": True}),
    )
    monkeypatch.setattr("app.main.get_legacy_memory_max_entry_id", AsyncMock(return_value=0))
    monkeypatch.setattr(
        "app.main.import_legacy_memory_to_openviking",
        AsyncMock(
            return_value={
                "complete": True,
                "max_memory_entry_id": 0,
                "sessions": 0,
                "messages": 0,
                "summaries": 0,
                "skipped_sessions": 0,
            }
        ),
    )
    monkeypatch.setattr("app.main.set_runtime_state", AsyncMock(return_value=None))
    monkeypatch.setattr("app.main.sync_workspace_resources", AsyncMock(return_value={"synced": 0}))
    monkeypatch.setattr("app.main.start_scheduler", lambda: None)
    monkeypatch.setattr("app.main.bootstrap_agent_jobs", AsyncMock(return_value=None))
    monkeypatch.setattr("app.main.shutdown_scheduler", lambda: None)
    monkeypatch.setattr("app.main.close_all_clients", AsyncMock(return_value=None))
    monkeypatch.setattr("app.main.close_openviking_client", AsyncMock(return_value=None))


@pytest_asyncio.fixture(autouse=True)
async def _reset_test_database():
    from app.database import engine, init_db

    TEST_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(TEST_ARCHIVE_DIR, ignore_errors=True)
    await engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    await init_db()
    yield
    await engine.dispose()
