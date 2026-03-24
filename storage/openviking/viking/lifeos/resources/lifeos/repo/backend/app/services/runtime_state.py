"""Internal runtime state persisted in SQLite for health and migration tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import RuntimeState

OPENVIKING_MEMORY_IMPORT_STATE_KEY = "openviking_memory_import"
OPENVIKING_WORKSPACE_SYNC_STATE_KEY = "openviking_workspace_sync"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def get_runtime_state(key: str) -> RuntimeState | None:
    async with async_session() as db:
        result = await db.execute(select(RuntimeState).where(RuntimeState.key == key))
        return result.scalar_one_or_none()


async def get_runtime_state_value(key: str) -> dict[str, Any] | None:
    row = await get_runtime_state(key)
    if not row:
        return None
    value = row.value_json
    return value if isinstance(value, dict) else None


async def set_runtime_state(key: str, value: dict[str, Any]) -> RuntimeState:
    async with async_session() as db:
        row = await db.get(RuntimeState, key)
        if not row:
            row = RuntimeState(key=key)
        row.value_json = value
        row.updated_at = _now_utc()
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row
