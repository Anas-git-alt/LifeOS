"""User profile service."""

from typing import Any

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import ProfileUpdate, UserProfile

DEFAULT_SLEEP_WIND_DOWN_CHECKLIST = [
    "Dim lights and put phone away",
    "Set tomorrow's first step",
    "Brush teeth and make wudu",
    "Get into bed on time",
]


def _normalize_sleep_checklist(value: Any) -> list[str]:
    if not value:
        return list(DEFAULT_SLEEP_WIND_DOWN_CHECKLIST)
    return [str(item).strip() for item in value if str(item).strip()] or list(DEFAULT_SLEEP_WIND_DOWN_CHECKLIST)


async def get_or_create_profile() -> UserProfile:
    async with async_session() as db:
        result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = result.scalar_one_or_none()
        if profile:
            if not profile.sleep_wind_down_checklist_json:
                profile.sleep_wind_down_checklist_json = list(DEFAULT_SLEEP_WIND_DOWN_CHECKLIST)
                await db.commit()
                await db.refresh(profile)
            return profile
        profile = UserProfile(
            id=1,
            timezone=settings.timezone,
            city=settings.prayer_city,
            country=settings.prayer_country,
            prayer_method=settings.prayer_method,
            quiet_hours_start=settings.quiet_hours_start,
            quiet_hours_end=settings.quiet_hours_end,
            nudge_mode=settings.nudge_mode,
            sleep_bedtime_target="23:30",
            sleep_wake_target="07:30",
            sleep_caffeine_cutoff="15:00",
            sleep_wind_down_checklist_json=list(DEFAULT_SLEEP_WIND_DOWN_CHECKLIST),
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile


async def update_profile(data: ProfileUpdate) -> UserProfile:
    async with async_session() as db:
        result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfile(
                id=1,
                sleep_bedtime_target="23:30",
                sleep_wake_target="07:30",
                sleep_caffeine_cutoff="15:00",
                sleep_wind_down_checklist_json=list(DEFAULT_SLEEP_WIND_DOWN_CHECKLIST),
            )
            db.add(profile)
            await db.flush()
        updates = data.model_dump(exclude_unset=True)
        if "sleep_wind_down_checklist" in updates:
            profile.sleep_wind_down_checklist_json = _normalize_sleep_checklist(updates.pop("sleep_wind_down_checklist"))
        for key, value in updates.items():
            setattr(profile, key, value)
        if not profile.sleep_wind_down_checklist_json:
            profile.sleep_wind_down_checklist_json = list(DEFAULT_SLEEP_WIND_DOWN_CHECKLIST)
        await db.commit()
        await db.refresh(profile)
        return profile
