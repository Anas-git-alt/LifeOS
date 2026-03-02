"""Quran page-based reading log with auto-resume bookmark."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import async_session
from app.models import QuranBookmark, QuranReading, QuranReadingRequest
from app.services.profile import get_or_create_profile

TOTAL_PAGES = 604


async def get_or_create_bookmark() -> QuranBookmark:
    async with async_session() as db:
        result = await db.execute(select(QuranBookmark).where(QuranBookmark.id == 1))
        bookmark = result.scalar_one_or_none()
        if not bookmark:
            bookmark = QuranBookmark(id=1, current_page=1)
            db.add(bookmark)
            await db.commit()
            await db.refresh(bookmark)
        return bookmark


async def log_reading(data: QuranReadingRequest) -> dict:
    """Log a Quran reading session. Auto-resumes from bookmark if start_page is None."""
    profile = await get_or_create_profile()
    tz = ZoneInfo(profile.timezone)
    today = datetime.now(timezone.utc).astimezone(tz).date()

    bookmark = await get_or_create_bookmark()
    start_page = data.start_page if data.start_page is not None else bookmark.current_page
    end_page = data.end_page

    if start_page < 1 or start_page > TOTAL_PAGES:
        raise ValueError(f"start_page must be between 1 and {TOTAL_PAGES}")
    if end_page < 1 or end_page > TOTAL_PAGES:
        raise ValueError(f"end_page must be between 1 and {TOTAL_PAGES}")

    # Calculate pages read (handle wrap-around: reading from page 600 to page 5)
    if end_page >= start_page:
        pages_read = end_page - start_page + 1
    else:
        pages_read = (TOTAL_PAGES - start_page + 1) + end_page

    async with async_session() as db:
        reading = QuranReading(
            local_date=today,
            start_page=start_page,
            end_page=end_page,
            note=data.note,
            source=data.source,
        )
        db.add(reading)

        # Update bookmark to next page
        next_page = (end_page % TOTAL_PAGES) + 1
        result = await db.execute(select(QuranBookmark).where(QuranBookmark.id == 1))
        bm = result.scalar_one_or_none()
        if bm:
            bm.current_page = next_page
            bm.updated_at = datetime.now(timezone.utc)
        else:
            db.add(QuranBookmark(id=1, current_page=next_page))

        await db.commit()
        await db.refresh(reading)

    return {
        "id": reading.id,
        "local_date": reading.local_date.strftime("%Y-%m-%d"),
        "start_page": reading.start_page,
        "end_page": reading.end_page,
        "pages_read": pages_read,
        "note": reading.note,
        "source": reading.source,
    }


async def get_progress() -> dict:
    """Return overall Quran reading progress and recent sessions."""
    bookmark = await get_or_create_bookmark()

    async with async_session() as db:
        # Total pages read
        total_result = await db.execute(
            select(
                func.sum(
                    func.case(
                        (
                            QuranReading.end_page >= QuranReading.start_page,
                            QuranReading.end_page - QuranReading.start_page + 1,
                        ),
                        else_=TOTAL_PAGES - QuranReading.start_page + 1 + QuranReading.end_page,
                    )
                )
            )
        )
        total_pages_read = total_result.scalar() or 0

        # Recent readings (last 10)
        recent_result = await db.execute(
            select(QuranReading).order_by(QuranReading.created_at.desc()).limit(10)
        )
        recent = list(recent_result.scalars().all())

    completion_pct = round((total_pages_read / TOTAL_PAGES) * 100, 2) if TOTAL_PAGES else 0.0

    recent_list = []
    for r in recent:
        if r.end_page >= r.start_page:
            pr = r.end_page - r.start_page + 1
        else:
            pr = (TOTAL_PAGES - r.start_page + 1) + r.end_page
        recent_list.append({
            "id": r.id,
            "local_date": r.local_date.strftime("%Y-%m-%d"),
            "start_page": r.start_page,
            "end_page": r.end_page,
            "pages_read": pr,
            "note": r.note,
            "source": r.source,
        })

    return {
        "current_page": bookmark.current_page,
        "total_pages": TOTAL_PAGES,
        "pages_read_total": int(total_pages_read),
        "completion_pct": completion_pct,
        "recent_readings": recent_list,
    }
