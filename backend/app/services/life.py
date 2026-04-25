"""Life item and agenda services."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import async_session
from app.models import (
    AuditLog,
    DailyLogCreate,
    DailyScorecard,
    IntakeEntry,
    LifeCheckin,
    LifeCheckinCreate,
    LifeItem,
    LifeItemCreate,
    LifeItemUpdate,
    ScheduledJob,
    SharedMemoryProposal,
    UserProfile,
)
from app.services.commitments import disable_follow_up_job, resolve_job_follow_up_due_at, upsert_follow_up_job
from app.services.prayer_service import get_today_schedule
from app.services.system_settings import get_data_start_date

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
TRAINING_STATUSES = {"done", "rest", "missed"}
DEFAULT_SLEEP_PROTOCOL = {
    "bedtime_target": "23:30",
    "wake_target": "07:30",
    "caffeine_cutoff": "15:00",
    "wind_down_checklist": [
        "Dim lights and put phone away",
        "Set tomorrow's first step",
        "Brush teeth and make wudu",
        "Get into bed on time",
    ],
}
ACCOUNTABILITY_METRICS = (
    {"key": "sleep", "label": "Sleep 7h+", "deadline_hour": 12},
    {"key": "hydration", "label": "Hydration 2+", "deadline_hour": 21},
    {"key": "protein", "label": "Protein", "deadline_hour": 21},
    {"key": "training", "label": "Train/Rest Set", "deadline_hour": 18},
    {"key": "family", "label": "Family Action", "deadline_hour": 18},
    {"key": "priority", "label": "Priority Done", "deadline_hour": 20},
    {"key": "shutdown", "label": "Shutdown", "deadline_hour": 23},
)


def _resolve_tz(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("UTC")


async def list_life_items(domain: str | None = None, status: str | None = None) -> list[LifeItem]:
    async with async_session() as db:
        query = select(LifeItem).order_by(LifeItem.updated_at.desc())
        if domain:
            query = query.where(LifeItem.domain == domain)
        if status:
            query = query.where(LifeItem.status == status)
        result = await db.execute(query)
        return list(result.scalars().all())


async def create_life_item(data: LifeItemCreate) -> LifeItem:
    async with async_session() as db:
        dump = data.model_dump()
        if "priority_factors" in dump:
            dump["priority_factors_json"] = dump.pop("priority_factors")
        if "context_links" in dump:
            dump["context_links_json"] = dump.pop("context_links")
        # Parse start_date string to date object
        start_date_raw = dump.pop("start_date", None)
        if start_date_raw and isinstance(start_date_raw, str):
            dump["start_date"] = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
        elif start_date_raw is None:
            dump["start_date"] = None
        item = LifeItem(**dump)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item


async def update_life_item(item_id: int, data: LifeItemUpdate) -> LifeItem | None:
    async with async_session() as db:
        result = await db.execute(select(LifeItem).where(LifeItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return None
        previous_status = item.status
        previous_due_at = item.due_at
        for key, value in data.model_dump(exclude_unset=True).items():
            if key == "priority_factors":
                key = "priority_factors_json"
            elif key == "context_links":
                key = "context_links_json"
            setattr(item, key, value)
        if item.status == "open" and previous_status != "open":
            db.add(
                AuditLog(
                    agent_name="commitment-loop",
                    action="life_item_reopened",
                    details=f"item_id={item.id}",
                    status="completed",
                )
            )
        await db.commit()
        await db.refresh(item)
    if item.status in {"done", "missed"}:
        await disable_follow_up_job(item.id, reason=f"status_changed:{item.status}")
    elif item.follow_up_job_id and (previous_status != item.status or previous_due_at != item.due_at):
        await upsert_follow_up_job(item.id)
    return item


async def add_checkin(item_id: int, data: LifeCheckinCreate) -> tuple[LifeCheckin | None, LifeItem | None]:
    async with async_session() as db:
        result = await db.execute(select(LifeItem).where(LifeItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return None, None
        checkin = LifeCheckin(
            life_item_id=item_id,
            result=data.result,
            note=data.note,
        )
        db.add(checkin)
        if data.result == "done":
            item.status = "done"
        elif data.result == "missed":
            item.status = "missed"
        await db.commit()
        await db.refresh(checkin)
        await db.refresh(item)
    if data.result in {"done", "missed"}:
        await disable_follow_up_job(item_id, reason=f"checkin:{data.result}")
    return checkin, item


async def snooze_life_item(
    item_id: int,
    *,
    due_at: datetime,
    timezone_name: str | None = None,
    source: str = "api",
    note: str | None = None,
) -> LifeItem | None:
    async with async_session() as db:
        result = await db.execute(select(LifeItem).where(LifeItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return None
        previous_status = item.status
        item.due_at = due_at.replace(tzinfo=None) if due_at.tzinfo else due_at
        item.status = "open"
        details = f"item_id={item.id} due_at={item.due_at.isoformat()} source={source}"
        if note:
            details = f"{details} note={note.strip()[:200]}"
        db.add(
            AuditLog(
                agent_name="commitment-loop",
                action="life_item_snoozed",
                details=details,
                status="completed",
            )
        )
        if previous_status != "open":
            db.add(
                AuditLog(
                    agent_name="commitment-loop",
                    action="life_item_reopened",
                    details=f"item_id={item.id} source=snooze",
                    status="completed",
                )
            )
        await db.commit()
        await db.refresh(item)
    await upsert_follow_up_job(item.id, timezone_name=timezone_name)
    async with async_session() as db:
        refreshed = await db.execute(select(LifeItem).where(LifeItem.id == item_id))
        return refreshed.scalar_one_or_none()


def _coerce_due_to_local_date(item: LifeItem, tz: ZoneInfo):
    if not item.due_at:
        return None
    due_dt = item.due_at
    if due_dt.tzinfo is None:
        due_dt = due_dt.replace(tzinfo=timezone.utc)
    else:
        due_dt = due_dt.astimezone(timezone.utc)
    return due_dt.astimezone(tz).date()


def _coerce_local_date(value: datetime | None, tz: ZoneInfo) -> date | None:
    if not value:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def _coerce_aware_utc(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_local_clock(value: datetime | None, tz: ZoneInfo) -> str:
    aware = _coerce_aware_utc(value)
    if not aware:
        return "unknown time"
    return aware.astimezone(tz).strftime("%H:%M")


def _serialize_life_item(
    item: LifeItem,
    *,
    focus_reason: str | None = None,
    follow_up_due_at: datetime | None = None,
) -> dict:
    return {
        "id": item.id,
        "domain": item.domain,
        "kind": item.kind,
        "title": item.title,
        "notes": item.notes,
        "priority": item.priority,
        "status": item.status,
        "due_at": item.due_at,
        "start_date": item.start_date.isoformat() if item.start_date else None,
        "recurrence_rule": item.recurrence_rule,
        "source_agent": item.source_agent,
        "risk_level": item.risk_level,
        "follow_up_job_id": item.follow_up_job_id,
        "priority_score": getattr(item, "priority_score", 50),
        "priority_reason": getattr(item, "priority_reason", None),
        "priority_factors": getattr(item, "priority_factors_json", None),
        "context_links": getattr(item, "context_links_json", None) or [],
        "last_prioritized_at": getattr(item, "last_prioritized_at", None),
        "focus_reason": focus_reason,
        "follow_up_due_at": follow_up_due_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
 

def _focus_rank_details(
    item: LifeItem,
    *,
    tz: ZoneInfo,
    today_date: date,
    now_local: datetime,
    follow_up_due_at: datetime | None,
) -> dict:
    due_local = _coerce_due_to_local_date(item, tz)
    follow_up_local_date = _coerce_local_date(follow_up_due_at, tz)
    now_utc = now_local.astimezone(timezone.utc)
    follow_up_utc = _coerce_aware_utc(follow_up_due_at)
    follow_up_local = follow_up_utc.astimezone(tz) if follow_up_utc else None
    due_utc = _coerce_aware_utc(item.due_at)

    if due_utc is not None and due_utc <= now_utc:
        category = 0
        reason = f"Deadline overdue since {_format_local_clock(due_utc, tz)}."
        secondary = due_utc.timestamp()
    elif due_utc is not None and due_utc <= now_utc + timedelta(hours=2):
        category = 1
        reason = f"Due soon at {_format_local_clock(due_utc, tz)}."
        secondary = due_utc.timestamp()
    elif follow_up_utc is not None and follow_up_utc <= now_utc:
        category = 2
        reason = f"Follow-up overdue since {_format_local_clock(follow_up_utc, tz)}."
        secondary = follow_up_utc.timestamp()
    elif follow_up_local_date is not None and follow_up_local_date <= today_date:
        category = 3
        reason = f"Follow-up due today at {_format_local_clock(follow_up_utc, tz)}."
        secondary = follow_up_utc.timestamp() if follow_up_utc else now_utc.timestamp()
    elif due_local == today_date:
        category = 4
        reason = f"Due today at {_format_local_clock(due_utc, tz)}."
        secondary = due_utc.timestamp() if due_utc else 0
    elif getattr(item, "priority_score", 50) >= 75 or item.priority == "high":
        category = 5
        reason = getattr(item, "priority_reason", None) or "High-priority open commitment."
        secondary = -float(getattr(item, "priority_score", 50) or 50)
    elif due_utc is not None:
        category = 6
        reason = "Upcoming deadline."
        secondary = due_utc.timestamp()
    else:
        category = 7
        reason = getattr(item, "priority_reason", None) or "Oldest untouched open commitment."
        secondary = -float(getattr(item, "priority_score", 50) or 50)

    tertiary = (_coerce_aware_utc(item.updated_at) or now_local.astimezone(timezone.utc)).timestamp()
    return {
        "raw": item,
        "due_local": due_local,
        "focus_reason": reason,
        "follow_up_due_at": follow_up_due_at,
        "sort_key": (category, secondary, tertiary, item.id),
    }


async def _get_profile_context(db) -> tuple[UserProfile | None, str, ZoneInfo, datetime]:
    profile_result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
    profile = profile_result.scalar_one_or_none()
    timezone_name = profile.timezone if profile else "Africa/Casablanca"
    tz = _resolve_tz(timezone_name)
    now_local = datetime.now(timezone.utc).astimezone(tz)
    return profile, timezone_name, tz, now_local


async def _get_or_create_daily_scorecard(db, *, local_date, timezone_name: str) -> tuple[DailyScorecard, bool]:
    result = await db.execute(select(DailyScorecard).where(DailyScorecard.local_date == local_date))
    scorecard = result.scalar_one_or_none()
    if scorecard:
        scorecard.timezone = timezone_name
        return scorecard, False
    scorecard = DailyScorecard(
        local_date=local_date,
        timezone=timezone_name,
        meals_count=0,
        hydration_count=0,
        shutdown_done=False,
        protein_hit=False,
        family_action_done=False,
        top_priority_completed_count=0,
        rescue_status="watch",
        notes_json={},
    )
    db.add(scorecard)
    await db.flush()
    return scorecard, True


def _scorecard_notes(scorecard: DailyScorecard) -> dict:
    return dict(scorecard.notes_json or {})


def _build_sleep_protocol(profile: UserProfile | None, scorecard: DailyScorecard | None) -> dict:
    sleep_summary = dict(getattr(scorecard, "sleep_summary_json", None) or {})
    checklist = list(getattr(profile, "sleep_wind_down_checklist_json", None) or [])
    if not checklist:
        checklist = list(DEFAULT_SLEEP_PROTOCOL["wind_down_checklist"])

    return {
        "bedtime_target": getattr(profile, "sleep_bedtime_target", None) or DEFAULT_SLEEP_PROTOCOL["bedtime_target"],
        "wake_target": getattr(profile, "sleep_wake_target", None) or DEFAULT_SLEEP_PROTOCOL["wake_target"],
        "caffeine_cutoff": getattr(profile, "sleep_caffeine_cutoff", None) or DEFAULT_SLEEP_PROTOCOL["caffeine_cutoff"],
        "wind_down_checklist": checklist,
        "sleep_hours_logged": scorecard.sleep_hours if scorecard else None,
        "bedtime_logged": sleep_summary.get("bedtime"),
        "wake_time_logged": sleep_summary.get("wake_time"),
    }


def _metric_hit(metric_key: str, scorecard: DailyScorecard | None) -> bool:
    if scorecard is None:
        return False
    if metric_key == "sleep":
        return scorecard.sleep_hours is not None and scorecard.sleep_hours >= 7
    if metric_key == "hydration":
        return scorecard.hydration_count >= 2
    if metric_key == "protein":
        return bool(scorecard.protein_hit)
    if metric_key == "training":
        return scorecard.training_status in {"done", "rest"}
    if metric_key == "family":
        return bool(scorecard.family_action_done)
    if metric_key == "priority":
        return scorecard.top_priority_completed_count >= 1
    if metric_key == "shutdown":
        return bool(scorecard.shutdown_done)
    return False


def _metric_status_for_date(
    metric: dict,
    scorecard: DailyScorecard | None,
    *,
    current_date: date,
    today_date: date,
    now_local: datetime,
) -> str:
    if _metric_hit(metric["key"], scorecard):
        return "hit"
    if current_date != today_date:
        return "miss"
    if now_local.hour >= metric["deadline_hour"]:
        return "miss"
    return "pending"


def _calculate_metric_streak(
    metric: dict,
    *,
    scorecards_by_date: dict[date, DailyScorecard],
    data_start_date: date,
    today_date: date,
    now_local: datetime,
) -> int:
    streak = 0
    current_date = today_date

    while current_date >= data_start_date:
        status = _metric_status_for_date(
            metric,
            scorecards_by_date.get(current_date),
            current_date=current_date,
            today_date=today_date,
            now_local=now_local,
        )
        if current_date == today_date and status == "pending":
            current_date -= timedelta(days=1)
            continue
        if status != "hit":
            break
        streak += 1
        current_date -= timedelta(days=1)

    return streak


def _count_metric_hits(
    metric: dict,
    *,
    scorecards_by_date: dict[date, DailyScorecard],
    start_date: date,
    end_date: date,
) -> int:
    if end_date < start_date:
        return 0

    hits = 0
    current_date = start_date
    while current_date <= end_date:
        if _metric_hit(metric["key"], scorecards_by_date.get(current_date)):
            hits += 1
        current_date += timedelta(days=1)
    return hits


def _build_day_completion(
    *,
    current_date: date,
    scorecard: DailyScorecard | None,
    today_date: date,
    now_local: datetime,
) -> dict:
    hits = sum(
        1
        for metric in ACCOUNTABILITY_METRICS
        if _metric_status_for_date(
            metric,
            scorecard,
            current_date=current_date,
            today_date=today_date,
            now_local=now_local,
        )
        == "hit"
    )
    total = len(ACCOUNTABILITY_METRICS)
    completion_pct = round((hits / total) * 100) if total else 0
    return {
        "date": current_date,
        "hits": hits,
        "total": total,
        "completion_pct": completion_pct,
    }


async def _build_accountability_summary(
    db,
    *,
    data_start_date: date,
    today_date: date,
    now_local: datetime,
) -> dict:
    history_result = await db.execute(
        select(DailyScorecard)
        .where(DailyScorecard.local_date >= data_start_date)
        .where(DailyScorecard.local_date <= today_date)
        .order_by(DailyScorecard.local_date.asc())
    )
    history = list(history_result.scalars().all())
    scorecards_by_date = {row.local_date: row for row in history}

    last_7_start = max(data_start_date, today_date - timedelta(days=6))
    streaks = []
    for metric in ACCOUNTABILITY_METRICS:
        streaks.append(
            {
                "key": metric["key"],
                "label": metric["label"],
                "current_streak": _calculate_metric_streak(
                    metric,
                    scorecards_by_date=scorecards_by_date,
                    data_start_date=data_start_date,
                    today_date=today_date,
                    now_local=now_local,
                ),
                "hits_last_7": _count_metric_hits(
                    metric,
                    scorecards_by_date=scorecards_by_date,
                    start_date=last_7_start,
                    end_date=today_date,
                ),
                "today_status": _metric_status_for_date(
                    metric,
                    scorecards_by_date.get(today_date),
                    current_date=today_date,
                    today_date=today_date,
                    now_local=now_local,
                ),
            }
        )

    completed_end = today_date - timedelta(days=1)
    recent_days: list[dict] = []
    if completed_end >= data_start_date:
        completed_start = max(data_start_date, completed_end - timedelta(days=6))
        current_date = completed_start
        while current_date <= completed_end:
            recent_days.append(
                _build_day_completion(
                    current_date=current_date,
                    scorecard=scorecards_by_date.get(current_date),
                    today_date=today_date,
                    now_local=now_local,
                )
            )
            current_date += timedelta(days=1)

    best_day = None
    if recent_days:
        best_day = max(recent_days, key=lambda day: (day["completion_pct"], day["hits"], day["date"]))
    average_completion_pct = (
        round(sum(day["completion_pct"] for day in recent_days) / len(recent_days))
        if recent_days
        else 0
    )

    return {
        "streaks": streaks,
        "trend_summary": {
            "window_days": 7,
            "average_completion_pct": average_completion_pct,
            "best_day": best_day,
            "recent_days": recent_days,
        },
    }


async def _load_open_items_snapshot(db, *, tz: ZoneInfo, today_date) -> dict:
    open_items_result = await db.execute(
        select(LifeItem).where(LifeItem.status == "open").order_by(LifeItem.updated_at.desc())
    )
    open_items = list(open_items_result.scalars().all())
    now_local = datetime.now(timezone.utc).astimezone(tz)

    follow_up_ids = [item.follow_up_job_id for item in open_items if item.follow_up_job_id]
    job_rows: list[ScheduledJob] = []
    if follow_up_ids:
        jobs_result = await db.execute(select(ScheduledJob).where(ScheduledJob.id.in_(follow_up_ids)))
        job_rows = list(jobs_result.scalars().all())
    jobs_by_id = {row.id: row for row in job_rows}

    ranked = []
    for item in open_items:
        follow_up_due_at = resolve_job_follow_up_due_at(jobs_by_id.get(item.follow_up_job_id))
        ranked.append(
            _focus_rank_details(
                item,
                tz=tz,
                today_date=today_date,
                now_local=now_local,
                follow_up_due_at=follow_up_due_at,
            )
        )

    ranked.sort(key=lambda row: row["sort_key"])
    top_focus = [row["raw"] for row in ranked[:3]]
    top_focus_display = [
        _serialize_life_item(
            row["raw"],
            focus_reason=row["focus_reason"],
            follow_up_due_at=row["follow_up_due_at"],
        )
        for row in ranked[:3]
    ]
    due_today = [row["raw"] for row in ranked if row["due_local"] == today_date]
    due_today_display = [
        _serialize_life_item(
            row["raw"],
            focus_reason=row["focus_reason"],
            follow_up_due_at=row["follow_up_due_at"],
        )
        for row in ranked
        if row["due_local"] == today_date
    ]
    overdue = [row["raw"] for row in ranked if row["due_local"] is not None and row["due_local"] < today_date]
    overdue_display = [
        _serialize_life_item(
            row["raw"],
            focus_reason=row["focus_reason"],
            follow_up_due_at=row["follow_up_due_at"],
        )
        for row in ranked
        if row["due_local"] is not None and row["due_local"] < today_date
    ]

    domain_counts_result = await db.execute(
        select(LifeItem.domain, func.count(LifeItem.id))
        .where(LifeItem.status == "open")
        .group_by(LifeItem.domain)
    )
    domain_summary = {domain: count for domain, count in domain_counts_result.all()}
    return {
        "open_items": open_items,
        "top_focus": top_focus,
        "top_focus_display": top_focus_display,
        "due_today": due_today,
        "due_today_display": due_today_display,
        "overdue": overdue,
        "overdue_display": overdue_display,
        "domain_summary": domain_summary,
    }


async def _load_intake_snapshot(db) -> dict:
    intake_counts_result = await db.execute(
        select(IntakeEntry.status, func.count(IntakeEntry.id))
        .group_by(IntakeEntry.status)
    )
    intake_summary = {status: count for status, count in intake_counts_result.all()}

    ready_intake_result = await db.execute(
        select(IntakeEntry)
        .where(IntakeEntry.status.in_(["ready", "clarifying"]))
        .order_by(IntakeEntry.updated_at.desc(), IntakeEntry.id.desc())
        .limit(3)
    )
    ready_intake = list(ready_intake_result.scalars().all())
    return {"intake_summary": intake_summary, "ready_intake": ready_intake}


async def _load_memory_review_snapshot(db) -> list[SharedMemoryProposal]:
    result = await db.execute(
        select(SharedMemoryProposal)
        .where(SharedMemoryProposal.status == "pending")
        .order_by(SharedMemoryProposal.created_at.desc(), SharedMemoryProposal.id.desc())
        .limit(5)
    )
    return list(result.scalars().all())


async def _load_next_prayer_context() -> dict | None:
    try:
        schedule = await get_today_schedule()
    except Exception:
        return None

    next_prayer_name = schedule.get("next_prayer")
    if not next_prayer_name:
        return None
    for row in schedule.get("windows") or []:
        if row.get("prayer_name") == next_prayer_name:
            return {
                "name": next_prayer_name,
                "starts_at": row["starts_at"],
                "ends_at": row["ends_at"],
            }
    return None


def _build_rescue_plan(
    *,
    scorecard: DailyScorecard,
    now_local: datetime,
    top_focus: list[LifeItem],
    due_today: list[LifeItem],
    overdue: list[LifeItem],
    next_prayer: dict | None,
) -> dict:
    issues: list[str] = []
    actions: list[str] = []

    overdue_high = [item for item in overdue if item.priority == "high"]
    if overdue_high:
        issues.append("High-priority work is overdue.")
        actions.append(f"Clear or reschedule overdue priority: {overdue_high[0].title}")

    if now_local.hour >= 12 and scorecard.meals_count == 0:
        issues.append("No meals logged yet.")
        actions.append("Eat one solid meal before adding more work.")

    if now_local.hour >= 15 and scorecard.hydration_count < 2:
        issues.append("Hydration is behind.")
        actions.append("Log water twice in the next hour.")

    if now_local.hour >= 14 and scorecard.top_priority_completed_count == 0 and any(
        item.priority == "high" for item in top_focus + due_today
    ):
        issues.append("Top priorities still untouched.")
        actions.append("Finish one priority item before opening new loops.")

    if now_local.hour >= 18 and scorecard.training_status is None:
        issues.append("Training status still undecided.")
        actions.append("Choose training or explicit rest so day has a clear close.")

    if now_local.hour >= 18 and not scorecard.family_action_done:
        issues.append("No family action logged yet.")
        actions.append("Do one visible family action before late evening.")

    if now_local.hour >= 21 and not scorecard.shutdown_done:
        issues.append("Shutdown routine still open.")
        actions.append("Start shutdown now: close loops, set tomorrow's first step, go offline.")

    if next_prayer:
        actions.append(f"Protect {next_prayer['name']} window before schedule drifts the day.")

    deduped_actions: list[str] = []
    seen = set()
    for action in actions:
        if action in seen:
            continue
        deduped_actions.append(action)
        seen.add(action)
        if len(deduped_actions) >= 4:
            break

    if overdue_high or len(issues) >= 3:
        status = "rescue"
    elif issues:
        status = "watch"
    else:
        status = "on_track"

    if status == "on_track":
        headline = "Day is on track. Protect anchors and keep momentum."
    elif status == "watch":
        headline = issues[0]
    else:
        headline = "Day needs a rescue plan. Shrink scope and recover anchors first."

    return {
        "status": status,
        "headline": headline,
        "actions": deduped_actions,
    }


def _format_daily_log_message(kind: str, scorecard: DailyScorecard, rescue_plan: dict) -> str:
    training_label = scorecard.training_status or "unset"
    return (
        f"Logged {kind}. Meals {scorecard.meals_count} | water {scorecard.hydration_count} | "
        f"train {training_label} | priorities {scorecard.top_priority_completed_count} | "
        f"rescue {rescue_plan['status']}"
    )


def _apply_daily_log_to_scorecard(scorecard: DailyScorecard, data: DailyLogCreate) -> None:
    notes = _scorecard_notes(scorecard)
    note = (data.note or "").strip() or None

    if data.kind == "sleep":
        if data.hours is None and not data.bedtime and not data.wake_time and not note:
            raise ValueError("Sleep log needs hours, bedtime, wake time, or note.")
        scorecard.sleep_hours = data.hours
        summary = dict(scorecard.sleep_summary_json or {})
        if data.hours is not None:
            summary["hours"] = data.hours
        if data.bedtime:
            summary["bedtime"] = data.bedtime
        if data.wake_time:
            summary["wake_time"] = data.wake_time
        if note:
            summary["note"] = note
            notes["sleep_note"] = note
        scorecard.sleep_summary_json = summary or None
    elif data.kind == "meal":
        increment = data.count or 1
        scorecard.meals_count += increment
        protein_hit = data.protein_hit
        if protein_hit is None and note:
            protein_hit = "protein" in note.lower()
        scorecard.protein_hit = bool(scorecard.protein_hit or protein_hit)
        if note:
            notes["last_meal_note"] = note
    elif data.kind == "training":
        status = data.status or "done"
        if status not in TRAINING_STATUSES:
            raise ValueError("Training status must be one of: done, rest, missed.")
        scorecard.training_status = status
        if note:
            notes["training_note"] = note
    elif data.kind == "hydration":
        increment = data.count or 1
        scorecard.hydration_count += increment
        if note:
            notes["last_hydration_note"] = note
    elif data.kind == "shutdown":
        scorecard.shutdown_done = True if data.done is None else bool(data.done)
        if note:
            notes["shutdown_note"] = note
    elif data.kind == "family":
        scorecard.family_action_done = True if data.done is None else bool(data.done)
        if note:
            notes["family_note"] = note
    elif data.kind == "priority":
        increment = data.count or 1
        scorecard.top_priority_completed_count += increment
        if note:
            notes["priority_note"] = note

    scorecard.notes_json = notes or None


async def get_today_agenda() -> dict:
    data_start_date = await get_data_start_date()
    async with async_session() as db:
        profile, timezone_name, tz, now_local = await _get_profile_context(db)
        today_date = now_local.date()
        agenda_snapshot = await _load_open_items_snapshot(db, tz=tz, today_date=today_date)
        intake_snapshot = await _load_intake_snapshot(db)
        memory_review = await _load_memory_review_snapshot(db)
        scorecard, created = await _get_or_create_daily_scorecard(
            db,
            local_date=today_date,
            timezone_name=timezone_name,
        )
        next_prayer = await _load_next_prayer_context()
        rescue_plan = _build_rescue_plan(
            scorecard=scorecard,
            now_local=now_local,
            top_focus=agenda_snapshot["top_focus"],
            due_today=agenda_snapshot["due_today"],
            overdue=agenda_snapshot["overdue"],
            next_prayer=next_prayer,
        )
        accountability_summary = await _build_accountability_summary(
            db,
            data_start_date=data_start_date,
            today_date=today_date,
            now_local=now_local,
        )
        sleep_protocol = _build_sleep_protocol(profile, scorecard)

        if created or scorecard.rescue_status != rescue_plan["status"]:
            scorecard.rescue_status = rescue_plan["status"]
            await db.commit()
            await db.refresh(scorecard)

        return {
            "timezone": timezone_name,
            "now": now_local,
            "top_focus": agenda_snapshot.get("top_focus_display", agenda_snapshot["top_focus"]),
            "due_today": agenda_snapshot.get("due_today_display", agenda_snapshot["due_today"]),
            "overdue": agenda_snapshot.get("overdue_display", agenda_snapshot["overdue"]),
            "domain_summary": agenda_snapshot["domain_summary"],
            "intake_summary": intake_snapshot["intake_summary"],
            "ready_intake": intake_snapshot["ready_intake"],
            "memory_review": memory_review,
            "scorecard": scorecard,
            "next_prayer": next_prayer,
            "rescue_plan": rescue_plan,
            "sleep_protocol": sleep_protocol,
            "streaks": accountability_summary["streaks"],
            "trend_summary": accountability_summary["trend_summary"],
        }


async def log_daily_signal(data: DailyLogCreate) -> dict:
    data_start_date = await get_data_start_date()
    async with async_session() as db:
        profile, timezone_name, tz, now_local = await _get_profile_context(db)
        today_date = now_local.date()
        scorecard, _ = await _get_or_create_daily_scorecard(
            db,
            local_date=today_date,
            timezone_name=timezone_name,
        )
        _apply_daily_log_to_scorecard(scorecard, data)

        agenda_snapshot = await _load_open_items_snapshot(db, tz=tz, today_date=today_date)
        next_prayer = await _load_next_prayer_context()
        rescue_plan = _build_rescue_plan(
            scorecard=scorecard,
            now_local=now_local,
            top_focus=agenda_snapshot["top_focus"],
            due_today=agenda_snapshot["due_today"],
            overdue=agenda_snapshot["overdue"],
            next_prayer=next_prayer,
        )
        accountability_summary = await _build_accountability_summary(
            db,
            data_start_date=data_start_date,
            today_date=today_date,
            now_local=now_local,
        )
        sleep_protocol = _build_sleep_protocol(profile, scorecard)
        scorecard.rescue_status = rescue_plan["status"]
        await db.commit()
        await db.refresh(scorecard)

        return {
            "kind": data.kind,
            "message": _format_daily_log_message(data.kind, scorecard, rescue_plan),
            "scorecard": scorecard,
            "rescue_plan": rescue_plan,
            "sleep_protocol": sleep_protocol,
            "streaks": accountability_summary["streaks"],
            "trend_summary": accountability_summary["trend_summary"],
        }


async def get_goal_progress(item_id: int) -> dict | None:
    """Return progress data for a specific goal/life item."""
    data_start_date = await get_data_start_date()
    cutoff_dt = datetime.combine(data_start_date, datetime.min.time()).replace(tzinfo=None)
    async with async_session() as db:
        result = await db.execute(select(LifeItem).where(LifeItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return None

        checkins_result = await db.execute(
            select(LifeCheckin)
            .where(LifeCheckin.life_item_id == item_id)
            .where(LifeCheckin.timestamp >= cutoff_dt)
            .order_by(LifeCheckin.timestamp.desc())
        )
        checkins = list(checkins_result.scalars().all())

    days_since_start = None
    if item.start_date:
        effective_start = max(item.start_date, data_start_date)
        days_since_start = (datetime.now(timezone.utc).date() - effective_start).days

    done_count = sum(1 for c in checkins if c.result == "done")
    partial_count = sum(1 for c in checkins if c.result == "partial")
    missed_count = sum(1 for c in checkins if c.result == "missed")

    return {
        "item": item,
        "days_since_start": days_since_start,
        "checkin_count": len(checkins),
        "done_count": done_count,
        "partial_count": partial_count,
        "missed_count": missed_count,
        "checkins": [
            {
                "id": c.id,
                "result": c.result,
                "note": c.note,
                "timestamp": c.timestamp.isoformat() if c.timestamp else None,
            }
            for c in checkins[:50]
        ],
    }
