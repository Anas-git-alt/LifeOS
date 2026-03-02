"""Prayer accountability router."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.models import (
    AdhkarHabitRequest,
    DeenHabit,
    HabitLogResponse,
    PrayerCheckinRequest,
    PrayerCheckinResponse,
    PrayerRetroactiveCheckinRequest,
    PrayerScheduleTodayResponse,
    PrayerWeeklySummaryResponse,
    QuranHabitRequest,
    TahajjudHabitRequest,
)
from app.security import require_api_token
from app.services.deen_metrics import get_weekly_summary
from app.services.prayer_service import (
    get_due_prayer_nudges,
    get_due_prayer_reminders,
    get_today_schedule,
    log_prayer_checkin,
    log_prayer_checkin_retroactive,
    mark_prayer_nudge_sent,
    mark_prayer_reminder_sent,
)
from app.database import async_session

router = APIRouter()


@router.get("/schedule/today", response_model=PrayerScheduleTodayResponse, dependencies=[Depends(require_api_token)])
async def prayer_schedule_today():
    schedule = await get_today_schedule()
    return PrayerScheduleTodayResponse.model_validate(schedule)


@router.post("/checkin", response_model=PrayerCheckinResponse, dependencies=[Depends(require_api_token)])
async def prayer_checkin(data: PrayerCheckinRequest):
    try:
        return PrayerCheckinResponse.model_validate(await log_prayer_checkin(data))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/checkin/retroactive", response_model=PrayerCheckinResponse, dependencies=[Depends(require_api_token)])
async def prayer_checkin_retroactive(data: PrayerRetroactiveCheckinRequest):
    try:
        return PrayerCheckinResponse.model_validate(await log_prayer_checkin_retroactive(data))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/weekly-summary", response_model=PrayerWeeklySummaryResponse, dependencies=[Depends(require_api_token)])
async def prayer_weekly_summary():
    summary = await get_weekly_summary()
    return PrayerWeeklySummaryResponse.model_validate(summary)


@router.post("/habits/quran", response_model=HabitLogResponse, dependencies=[Depends(require_api_token)])
async def log_quran(data: QuranHabitRequest):
    async with async_session() as db:
        row = DeenHabit(
            local_date=datetime.strptime(data.date, "%Y-%m-%d").date(),
            habit_type="quran",
            value_json={"juz": data.juz, "pages": data.pages},
            done=True,
            source="command",
            note=data.note,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return HabitLogResponse(id=row.id, local_date=row.local_date.strftime("%Y-%m-%d"), habit_type=row.habit_type, done=row.done)


@router.post("/habits/tahajjud", response_model=HabitLogResponse, dependencies=[Depends(require_api_token)])
async def log_tahajjud(data: TahajjudHabitRequest):
    local_date = datetime.strptime(data.date, "%Y-%m-%d").date() if data.date else datetime.now(timezone.utc).date()
    async with async_session() as db:
        row = DeenHabit(
            local_date=local_date,
            habit_type="tahajjud",
            value_json=None,
            done=data.done,
            source="command",
            note=None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return HabitLogResponse(id=row.id, local_date=row.local_date.strftime("%Y-%m-%d"), habit_type=row.habit_type, done=row.done)


@router.post("/habits/adhkar", response_model=HabitLogResponse, dependencies=[Depends(require_api_token)])
async def log_adhkar(data: AdhkarHabitRequest):
    local_date = datetime.strptime(data.date, "%Y-%m-%d").date() if data.date else datetime.now(timezone.utc).date()
    async with async_session() as db:
        row = DeenHabit(
            local_date=local_date,
            habit_type=f"adhkar_{data.period}",
            value_json=None,
            done=data.done,
            source="command",
            note=None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return HabitLogResponse(id=row.id, local_date=row.local_date.strftime("%Y-%m-%d"), habit_type=row.habit_type, done=row.done)


@router.get("/due-reminders", dependencies=[Depends(require_api_token)])
async def due_prayer_reminders():
    return {"items": await get_due_prayer_reminders()}


@router.post("/reminder-sent", dependencies=[Depends(require_api_token)])
async def reminder_sent(payload: dict):
    await mark_prayer_reminder_sent(
        prayer_window_id=int(payload.get("window_id")),
        discord_message_id=str(payload.get("discord_message_id") or ""),
    )
    return {"ok": True}


@router.get("/due-nudges", dependencies=[Depends(require_api_token)])
async def due_prayer_nudges():
    return {"items": await get_due_prayer_nudges()}


@router.post("/nudge-sent", dependencies=[Depends(require_api_token)])
async def nudge_sent(payload: dict):
    await mark_prayer_nudge_sent(int(payload.get("window_id")))
    return {"ok": True}
