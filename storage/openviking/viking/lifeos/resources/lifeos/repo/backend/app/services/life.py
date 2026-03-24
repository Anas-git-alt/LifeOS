"""Life item and agenda services."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import async_session
from app.models import LifeCheckin, LifeCheckinCreate, LifeItem, LifeItemCreate, LifeItemUpdate, UserProfile
from app.services.system_settings import get_data_start_date

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


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
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        await db.commit()
        await db.refresh(item)
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
        return checkin, item


async def get_today_agenda() -> dict:
    async with async_session() as db:
        profile_result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
        profile = profile_result.scalar_one_or_none()
        timezone_name = profile.timezone if profile else "Africa/Casablanca"
        tz = _resolve_tz(timezone_name)
        now_local = datetime.now(timezone.utc).astimezone(tz)
        today_date = now_local.date()

        open_items_result = await db.execute(
            select(LifeItem).where(LifeItem.status == "open").order_by(LifeItem.updated_at.desc())
        )
        open_items = list(open_items_result.scalars().all())

        top_focus = sorted(
            open_items,
            key=lambda item: (
                PRIORITY_ORDER.get(item.priority, 1),
                item.due_at.timestamp() if item.due_at else 9999999999,
            ),
        )[:3]

        due_today = []
        overdue = []
        for item in open_items:
            if not item.due_at:
                continue
            due_dt = item.due_at
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
            else:
                due_dt = due_dt.astimezone(timezone.utc)
            due_local = due_dt.astimezone(tz).date()
            if due_local == today_date:
                due_today.append(item)
            elif due_local < today_date:
                overdue.append(item)

        domain_counts_result = await db.execute(
            select(LifeItem.domain, func.count(LifeItem.id))
            .where(LifeItem.status == "open")
            .group_by(LifeItem.domain)
        )
        domain_summary = {domain: count for domain, count in domain_counts_result.all()}

        return {
            "timezone": timezone_name,
            "now": now_local,
            "top_focus": top_focus,
            "due_today": due_today,
            "overdue": overdue,
            "domain_summary": domain_summary,
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
