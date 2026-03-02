"""Prayer schedules, check-ins, and reminder queue logic."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, func, or_, select

from app.database import async_session
from app.models import Agent, PrayerCheckin, PrayerCheckinRequest, PrayerReminder, PrayerRetroactiveCheckinRequest, PrayerWindow
from app.services.profile import get_or_create_profile

PRAYER_ORDER = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
VALID_STATUSES = {"on_time", "late", "missed", "unknown"}


def _parse_hhmm(raw: str) -> time:
    token = (raw or "").strip().split(" ")[0]
    hh, mm = token.split(":")
    return time(hour=int(hh), minute=int(mm))


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _format_date(dt: date) -> str:
    return dt.strftime("%Y-%m-%d")


async def _fetch_aladhan_timing(local_date: date, city: str, country: str, method: int) -> dict:
    ddmmyyyy = local_date.strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timingsByCity/{ddmmyyyy}"
    params = {"city": city, "country": country, "method": method}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    return payload["data"]


async def _get_prayer_channel_name() -> str:
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == "prayer-deen"))
        agent = result.scalar_one_or_none()
        if agent and agent.discord_channel:
            return agent.discord_channel
    return "prayer-tracker"


async def ensure_prayer_windows_for_date(local_date: date | None = None) -> list[PrayerWindow]:
    profile = await get_or_create_profile()
    tz = ZoneInfo(profile.timezone)
    target_date = local_date or datetime.now(timezone.utc).astimezone(tz).date()

    async with async_session() as db:
        existing = await db.execute(
            select(PrayerWindow)
            .where(PrayerWindow.local_date == target_date)
            .where(PrayerWindow.timezone == profile.timezone)
            .where(PrayerWindow.city == profile.city)
            .where(PrayerWindow.country == profile.country)
            .where(PrayerWindow.method == profile.prayer_method)
        )
        existing_rows = list(existing.scalars().all())
        if len(existing_rows) >= 5:
            return sorted(existing_rows, key=lambda row: PRAYER_ORDER.index(row.prayer_name))

        today_payload = await _fetch_aladhan_timing(target_date, profile.city, profile.country, profile.prayer_method)
        tomorrow_payload = await _fetch_aladhan_timing(
            target_date + timedelta(days=1), profile.city, profile.country, profile.prayer_method
        )

        today_timings = today_payload["timings"]
        tomorrow_timings = tomorrow_payload["timings"]
        hijri_month = int(today_payload["date"]["hijri"]["month"]["number"])
        is_ramadan = hijri_month == 9

        starts_local: dict[str, datetime] = {}
        for prayer in PRAYER_ORDER:
            starts_local[prayer] = datetime.combine(target_date, _parse_hhmm(today_timings[prayer]), tzinfo=tz)
        next_day_fajr = datetime.combine(target_date + timedelta(days=1), _parse_hhmm(tomorrow_timings["Fajr"]), tzinfo=tz)

        created: list[PrayerWindow] = []
        for idx, prayer in enumerate(PRAYER_ORDER):
            starts_at_utc = starts_local[prayer].astimezone(timezone.utc).replace(tzinfo=None)
            if idx < len(PRAYER_ORDER) - 1:
                end_local = starts_local[PRAYER_ORDER[idx + 1]]
            else:
                end_local = next_day_fajr
            ends_at_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

            row_result = await db.execute(
                select(PrayerWindow)
                .where(PrayerWindow.local_date == target_date)
                .where(PrayerWindow.prayer_name == prayer)
                .where(PrayerWindow.timezone == profile.timezone)
                .where(PrayerWindow.city == profile.city)
                .where(PrayerWindow.country == profile.country)
                .where(PrayerWindow.method == profile.prayer_method)
            )
            row = row_result.scalar_one_or_none()
            if not row:
                row = PrayerWindow(
                    local_date=target_date,
                    timezone=profile.timezone,
                    city=profile.city,
                    country=profile.country,
                    method=profile.prayer_method,
                    prayer_name=prayer,
                    starts_at_utc=starts_at_utc,
                    ends_at_utc=ends_at_utc,
                    hijri_month=hijri_month,
                    is_ramadan=is_ramadan,
                    source_payload_json=today_payload,
                )
                db.add(row)
            else:
                row.starts_at_utc = starts_at_utc
                row.ends_at_utc = ends_at_utc
                row.hijri_month = hijri_month
                row.is_ramadan = is_ramadan
                row.source_payload_json = today_payload
            created.append(row)

        await db.commit()
        for row in created:
            await db.refresh(row)
        return sorted(created, key=lambda row: PRAYER_ORDER.index(row.prayer_name))


def _choose_scored_status(status: str, is_retroactive: bool) -> str:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid prayer status '{status}'")
    if is_retroactive and status == "on_time":
        return "late"
    return status


async def _get_window_or_raise(prayer_date: date, prayer_name: str) -> PrayerWindow:
    await ensure_prayer_windows_for_date(prayer_date)
    async with async_session() as db:
        result = await db.execute(
            select(PrayerWindow)
            .where(PrayerWindow.local_date == prayer_date)
            .where(PrayerWindow.prayer_name == prayer_name)
        )
        window = result.scalar_one_or_none()
        if not window:
            raise ValueError("Prayer window not found")
        return window


async def log_prayer_checkin(data: PrayerCheckinRequest) -> dict:
    prayer_date = _parse_date(data.prayer_date)
    window = await _get_window_or_raise(prayer_date, data.prayer_name)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if now_utc > window.ends_at_utc:
        raise ValueError("Prayer window ended. Use /checkin/retroactive for late manual logs.")
    scored_status = _choose_scored_status(data.status, is_retroactive=False)

    async with async_session() as db:
        existing_result = await db.execute(select(PrayerCheckin).where(PrayerCheckin.prayer_window_id == window.id))
        existing = existing_result.scalar_one_or_none()
        if not existing:
            existing = PrayerCheckin(
                prayer_window_id=window.id,
                status_raw=data.status,
                status_scored=scored_status,
                reported_at_utc=now_utc,
                source=data.source,
                discord_user_id=data.discord_user_id,
                note=data.note,
                is_retroactive=False,
            )
            db.add(existing)
        else:
            existing.status_raw = data.status
            existing.status_scored = scored_status
            existing.reported_at_utc = now_utc
            existing.source = data.source
            existing.discord_user_id = data.discord_user_id
            existing.note = data.note
            existing.is_retroactive = False
            existing.retro_reason = None
        await db.commit()
        await db.refresh(existing)
    return {
        "prayer_date": _format_date(prayer_date),
        "prayer_name": data.prayer_name,
        "status_raw": existing.status_raw,
        "status_scored": existing.status_scored,
        "is_retroactive": existing.is_retroactive,
        "reported_at_utc": existing.reported_at_utc.replace(tzinfo=timezone.utc),
    }


async def log_prayer_checkin_retroactive(data: PrayerRetroactiveCheckinRequest) -> dict:
    prayer_date = _parse_date(data.prayer_date)
    window = await _get_window_or_raise(prayer_date, data.prayer_name)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    scored_status = _choose_scored_status(data.status, is_retroactive=True)

    async with async_session() as db:
        existing_result = await db.execute(select(PrayerCheckin).where(PrayerCheckin.prayer_window_id == window.id))
        existing = existing_result.scalar_one_or_none()
        if not existing:
            existing = PrayerCheckin(
                prayer_window_id=window.id,
                status_raw=data.status,
                status_scored=scored_status,
                reported_at_utc=now_utc,
                source=data.source,
                discord_user_id=data.discord_user_id,
                note=data.note,
                is_retroactive=True,
                retro_reason="manual_retroactive",
            )
            db.add(existing)
        else:
            existing.status_raw = data.status
            existing.status_scored = scored_status
            existing.reported_at_utc = now_utc
            existing.source = data.source
            existing.discord_user_id = data.discord_user_id
            existing.note = data.note
            existing.is_retroactive = True
            existing.retro_reason = "manual_retroactive"
        await db.commit()
        await db.refresh(existing)
    return {
        "prayer_date": _format_date(prayer_date),
        "prayer_name": data.prayer_name,
        "status_raw": existing.status_raw,
        "status_scored": existing.status_scored,
        "is_retroactive": existing.is_retroactive,
        "reported_at_utc": existing.reported_at_utc.replace(tzinfo=timezone.utc),
    }


async def get_today_schedule() -> dict:
    profile = await get_or_create_profile()
    tz = ZoneInfo(profile.timezone)
    now_local = datetime.now(timezone.utc).astimezone(tz)
    windows = await ensure_prayer_windows_for_date(now_local.date())

    next_prayer = None
    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    ordered = sorted(windows, key=lambda row: row.starts_at_utc)
    for row in ordered:
        if row.starts_at_utc > now_utc_naive:
            next_prayer = row.prayer_name
            break

    return {
        "date": _format_date(now_local.date()),
        "timezone": profile.timezone,
        "city": profile.city,
        "country": profile.country,
        "hijri_month": ordered[0].hijri_month if ordered else 1,
        "is_ramadan": bool(ordered[0].is_ramadan) if ordered else False,
        "next_prayer": next_prayer,
        "windows": [
            {
                "prayer_name": row.prayer_name,
                "starts_at": row.starts_at_utc.replace(tzinfo=timezone.utc),
                "ends_at": row.ends_at_utc.replace(tzinfo=timezone.utc),
            }
            for row in ordered
        ],
    }


async def auto_mark_unknown_expired() -> int:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session() as db:
        result = await db.execute(
            select(PrayerWindow)
            .outerjoin(PrayerCheckin, PrayerCheckin.prayer_window_id == PrayerWindow.id)
            .where(PrayerWindow.ends_at_utc <= now_utc)
            .where(PrayerCheckin.id.is_(None))
        )
        missing = list(result.scalars().all())
        for window in missing:
            db.add(
                PrayerCheckin(
                    prayer_window_id=window.id,
                    status_raw="unknown",
                    status_scored="unknown",
                    reported_at_utc=window.ends_at_utc,
                    source="system_autoclose",
                    is_retroactive=False,
                )
            )
        if missing:
            await db.commit()
        return len(missing)


async def get_due_prayer_reminders() -> list[dict]:
    schedule = await get_today_schedule()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    channel_name = await _get_prayer_channel_name()
    async with async_session() as db:
        result = await db.execute(
            select(PrayerWindow)
            .outerjoin(PrayerReminder, PrayerReminder.prayer_window_id == PrayerWindow.id)
            .where(PrayerWindow.local_date == _parse_date(schedule["date"]))
            .where(PrayerWindow.starts_at_utc <= now_utc)
            .where(PrayerWindow.ends_at_utc > now_utc)
            .where(PrayerReminder.id.is_(None))
        )
        windows = sorted(result.scalars().all(), key=lambda row: PRAYER_ORDER.index(row.prayer_name))
    due = []
    for window in windows:
        due.append(
            {
                "window_id": window.id,
                "prayer_date": _format_date(window.local_date),
                "prayer_name": window.prayer_name,
                "starts_at": window.starts_at_utc.replace(tzinfo=timezone.utc).isoformat(),
                "ends_at": window.ends_at_utc.replace(tzinfo=timezone.utc).isoformat(),
                "is_ramadan": bool(window.is_ramadan),
                "channel_name": channel_name,
            }
        )
    return due


async def mark_prayer_reminder_sent(prayer_window_id: int, discord_message_id: str | None) -> None:
    channel_name = await _get_prayer_channel_name()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session() as db:
        result = await db.execute(select(PrayerReminder).where(PrayerReminder.prayer_window_id == prayer_window_id))
        reminder = result.scalar_one_or_none()
        if not reminder:
            reminder = PrayerReminder(
                prayer_window_id=prayer_window_id,
                channel_name=channel_name,
                discord_message_id=discord_message_id,
                sent_at_utc=now_utc,
            )
            db.add(reminder)
        else:
            reminder.discord_message_id = discord_message_id
            reminder.sent_at_utc = now_utc
        await db.commit()


async def get_due_prayer_nudges() -> list[dict]:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now_utc + timedelta(minutes=10)
    async with async_session() as db:
        result = await db.execute(
            select(PrayerReminder, PrayerWindow)
            .join(PrayerWindow, PrayerWindow.id == PrayerReminder.prayer_window_id)
            .outerjoin(PrayerCheckin, PrayerCheckin.prayer_window_id == PrayerWindow.id)
            .where(PrayerReminder.deadline_nudge_sent_at_utc.is_(None))
            .where(PrayerWindow.ends_at_utc > now_utc)
            .where(PrayerWindow.ends_at_utc <= cutoff)
            .where(PrayerCheckin.id.is_(None))
        )
        pairs = result.all()
    return [
        {
            "window_id": window.id,
            "prayer_date": _format_date(window.local_date),
            "prayer_name": window.prayer_name,
            "channel_name": reminder.channel_name,
            "discord_message_id": reminder.discord_message_id,
            "ends_at": window.ends_at_utc.replace(tzinfo=timezone.utc).isoformat(),
        }
        for reminder, window in pairs
    ]


async def mark_prayer_nudge_sent(prayer_window_id: int) -> None:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session() as db:
        result = await db.execute(select(PrayerReminder).where(PrayerReminder.prayer_window_id == prayer_window_id))
        reminder = result.scalar_one_or_none()
        if reminder:
            reminder.deadline_nudge_sent_at_utc = now_utc
            await db.commit()


async def refresh_today_and_tomorrow_windows() -> None:
    profile = await get_or_create_profile()
    tz = ZoneInfo(profile.timezone)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    await ensure_prayer_windows_for_date(today)
    await ensure_prayer_windows_for_date(today + timedelta(days=1))
