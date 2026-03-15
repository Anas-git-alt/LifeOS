"""Deen metrics aggregation for weekly reports and agent context."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select

from app.database import async_session
from app.models import DeenHabit, PrayerCheckin, PrayerWindow, QuranReading
from app.services.profile import get_or_create_profile
from app.services.prayer_service import ensure_prayer_windows_for_date, get_today_schedule
from app.services.system_settings import get_data_start_date


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


async def get_weekly_summary() -> dict:
    profile = await get_or_create_profile()
    tz = ZoneInfo(profile.timezone)
    today = datetime.now(timezone.utc).astimezone(tz).date()
    start_date = today - timedelta(days=6)
    data_start_date = await get_data_start_date()
    if data_start_date > start_date:
        start_date = data_start_date

    days_span = max(0, (today - start_date).days + 1)
    for i in range(days_span):
        await ensure_prayer_windows_for_date(start_date + timedelta(days=i))

    async with async_session() as db:
        windows_result = await db.execute(
            select(PrayerWindow).where(PrayerWindow.local_date >= start_date).where(PrayerWindow.local_date <= today)
        )
        windows = list(windows_result.scalars().all())

        checkins_result = await db.execute(
            select(PrayerCheckin, PrayerWindow)
            .join(PrayerWindow, PrayerWindow.id == PrayerCheckin.prayer_window_id)
            .where(PrayerWindow.local_date >= start_date)
            .where(PrayerWindow.local_date <= today)
        )
        checkins_by_window = {window.id: checkin for checkin, window in checkins_result.all()}

        habits_result = await db.execute(
            select(DeenHabit).where(DeenHabit.local_date >= start_date).where(DeenHabit.local_date <= today)
        )
        habits = list(habits_result.scalars().all())

        # Quran pages from the new quran_readings table (page-based tracking)
        TOTAL_PAGES = 604
        quran_result = await db.execute(
            select(
                func.sum(
                    case(
                        (
                            QuranReading.end_page >= QuranReading.start_page,
                            QuranReading.end_page - QuranReading.start_page + 1,
                        ),
                        else_=TOTAL_PAGES - QuranReading.start_page + 1 + QuranReading.end_page,
                    )
                )
            ).where(
                QuranReading.local_date >= start_date,
                QuranReading.local_date <= today,
            )
        )
        quran_pages_total = int(quran_result.scalar() or 0)

    total_prayers = len(windows)
    on_time = 0
    late = 0
    missed = 0
    unknown = 0
    retroactive_count = 0
    for window in windows:
        checkin = checkins_by_window.get(window.id)
        if not checkin:
            unknown += 1
            continue
        if checkin.is_retroactive:
            retroactive_count += 1
        scored = checkin.status_scored
        if scored == "on_time":
            on_time += 1
        elif scored == "late":
            late += 1
        elif scored == "missed":
            missed += 1
        else:
            unknown += 1

    on_time_rate = round((on_time / total_prayers) * 100, 2) if total_prayers else 0.0
    completion_rate = round(((on_time + late) / total_prayers) * 100, 2) if total_prayers else 0.0

    quran_juz_max = 0
    tahajjud_done = 0
    adhkar_morning_done = 0
    adhkar_evening_done = 0
    for habit in habits:
        if habit.habit_type == "quran":
            # Legacy juz tracking only — pages are now sourced from quran_readings table above
            value = habit.value_json or {}
            quran_juz_max = max(quran_juz_max, int(value.get("juz", 0) or 0))
        elif habit.habit_type == "tahajjud" and habit.done:
            tahajjud_done += 1
        elif habit.habit_type == "adhkar_morning" and habit.done:
            adhkar_morning_done += 1
        elif habit.habit_type == "adhkar_evening" and habit.done:
            adhkar_evening_done += 1

    guidance: list[str] = []
    if on_time_rate < 70:
        guidance.append("Set a 10-minute pre-adhan prep routine to improve on-time consistency.")
    if unknown > 0:
        guidance.append("Use reactions immediately after each prayer to reduce unknown logs.")
    if quran_pages_total < 28:
        guidance.append("Increase Quran reading pace to at least 4 pages/day for steady khatma progress.")
    if tahajjud_done < 4:
        guidance.append("Aim for 4 tahajjud nights this week by fixing a simple pre-sleep plan.")
    if adhkar_morning_done < 5 or adhkar_evening_done < 5:
        guidance.append("Attach morning/evening adhkar to fixed anchors (after Fajr and after Maghrib).")

    is_ramadan = any(window.is_ramadan for window in windows)
    if is_ramadan:
        guidance.append("Ramadan mode: prioritize punctual salah, daily Quran target, and consistent night worship.")

    return {
        "start_date": _fmt(start_date),
        "end_date": _fmt(today),
        "total_prayers": total_prayers,
        "on_time": on_time,
        "late": late,
        "missed": missed,
        "unknown": unknown,
        "retroactive_count": retroactive_count,
        "on_time_rate": on_time_rate,
        "completion_rate": completion_rate,
        "is_ramadan": is_ramadan,
        "quran_pages_total": quran_pages_total,
        "quran_juz_max": quran_juz_max,
        "tahajjud_done": tahajjud_done,
        "tahajjud_target": 4,
        "adhkar_morning_done": adhkar_morning_done,
        "adhkar_evening_done": adhkar_evening_done,
        "guidance": guidance,
    }


async def build_prayer_agent_context() -> str:
    today = await get_today_schedule()
    week = await get_weekly_summary()
    windows = ", ".join([f"{w['prayer_name']} {w['starts_at'].strftime('%H:%M')}Z" for w in today["windows"]])
    return (
        "[PRAYER CONTEXT]\n"
        f"Location: {today['city']}, {today['country']} ({today['timezone']})\n"
        f"Date: {today['date']} | Ramadan: {'yes' if today['is_ramadan'] else 'no'}\n"
        f"Next prayer: {today['next_prayer'] or 'none'}\n"
        f"Today's windows UTC: {windows}\n"
        f"Weekly on-time: {week['on_time']}/{week['total_prayers']} ({week['on_time_rate']}%)\n"
        f"Late={week['late']}, Missed={week['missed']}, Unknown={week['unknown']}, Retroactive={week['retroactive_count']}\n"
        f"Quran pages this week: {week['quran_pages_total']}, max juz: {week['quran_juz_max']}\n"
        f"Tahajjud: {week['tahajjud_done']}/{week['tahajjud_target']}, "
        f"Adhkar morning/evening: {week['adhkar_morning_done']}/{week['adhkar_evening_done']}\n"
        "[END PRAYER CONTEXT]"
    )


async def build_weekly_deen_context() -> str:
    week = await get_weekly_summary()
    guidance = "\n".join(f"- {line}" for line in week["guidance"][:5]) if week["guidance"] else "- Keep current habits."
    return (
        "[DEEN WEEKLY METRICS]\n"
        f"Window: {week['start_date']} to {week['end_date']}\n"
        f"Prayer Accuracy: on-time {week['on_time']}/{week['total_prayers']} ({week['on_time_rate']}%)\n"
        f"Breakdown: late={week['late']}, missed={week['missed']}, unknown={week['unknown']}, retroactive={week['retroactive_count']}\n"
        f"Quran: total pages={week['quran_pages_total']} | max juz reached={week['quran_juz_max']}\n"
        f"Tahajjud: {week['tahajjud_done']}/{week['tahajjud_target']}\n"
        f"Adhkar: morning={week['adhkar_morning_done']}, evening={week['adhkar_evening_done']}\n"
        f"Ramadan mode: {'on' if week['is_ramadan'] else 'off'}\n"
        "Guidance:\n"
        f"{guidance}\n"
        "[END DEEN WEEKLY METRICS]"
    )
