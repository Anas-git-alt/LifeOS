"""Global runtime settings helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import SystemSettings, SystemSettingsUpdate, UserProfile
from app.services.events import publish_event

SAFE_DEFAULT_DATA_START_DATE = date(2026, 3, 2)


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("Africa/Casablanca")


async def _initial_data_start_date() -> date:
    async with async_session() as db:
        profile_result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = profile_result.scalar_one_or_none()
    timezone_name = profile.timezone if profile else settings.timezone
    local_date = datetime.now(timezone.utc).astimezone(_resolve_timezone(timezone_name)).date()
    return local_date or SAFE_DEFAULT_DATA_START_DATE


async def get_or_create_system_settings() -> SystemSettings:
    async with async_session() as db:
        result = await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
        row = result.scalar_one_or_none()
        if row:
            return row

        data_start = await _initial_data_start_date()
        row = SystemSettings(
            id=1,
            data_start_date=data_start or SAFE_DEFAULT_DATA_START_DATE,
            default_timezone=settings.timezone,
            autonomy_enabled=True,
            approval_required_for_mutations=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def update_system_settings(data: SystemSettingsUpdate) -> SystemSettings:
    async with async_session() as db:
        result = await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
        row = result.scalar_one_or_none()
        if not row:
            row = SystemSettings(
                id=1,
                data_start_date=await _initial_data_start_date(),
                default_timezone=settings.timezone,
                autonomy_enabled=True,
                approval_required_for_mutations=True,
            )
            db.add(row)
            await db.flush()

        updates = data.model_dump(exclude_unset=True)
        if "data_start_date" in updates and updates["data_start_date"]:
            row.data_start_date = _parse_date(str(updates["data_start_date"]))
            updates.pop("data_start_date", None)

        for key, value in updates.items():
            setattr(row, key, value)

        await db.commit()
        await db.refresh(row)
        await publish_event(
            "settings.updated",
            {"kind": "settings", "id": "global"},
            {
                "data_start_date": row.data_start_date.strftime("%Y-%m-%d"),
                "default_timezone": row.default_timezone,
                "autonomy_enabled": row.autonomy_enabled,
                "approval_required_for_mutations": row.approval_required_for_mutations,
            },
        )
        return row


async def get_data_start_date() -> date:
    row = await get_or_create_system_settings()
    if row.data_start_date:
        return row.data_start_date
    return SAFE_DEFAULT_DATA_START_DATE
