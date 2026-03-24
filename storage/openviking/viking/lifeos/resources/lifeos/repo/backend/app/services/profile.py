"""User profile service."""

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import ProfileUpdate, UserProfile


async def get_or_create_profile() -> UserProfile:
    async with async_session() as db:
        result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = result.scalar_one_or_none()
        if profile:
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
            profile = UserProfile(id=1)
            db.add(profile)
            await db.flush()
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, key, value)
        await db.commit()
        await db.refresh(profile)
        return profile
