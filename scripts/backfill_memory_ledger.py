#!/usr/bin/env python3
"""Backfill private memory ledger from open LifeOS items and recent user turns."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select

from app.database import async_session, init_db
from app.models import IntakeEntry, LifeItem, MemoryEntry
from app.services.memory_ledger import record_capture_memory, record_memory_event


async def _backfill_open_items() -> int:
    count = 0
    async with async_session() as db:
        result = await db.execute(
            select(IntakeEntry, LifeItem)
            .join(LifeItem, LifeItem.id == IntakeEntry.linked_life_item_id, isouter=True)
            .where((IntakeEntry.status != "processed") | (LifeItem.status == "open"))
            .order_by(IntakeEntry.updated_at.desc(), IntakeEntry.id.desc())
            .limit(300)
        )
        rows = list(result.all())
    for entry, item in rows:
        raw = entry.raw_text or entry.summary or entry.title or (item.notes if item else "") or (item.title if item else "")
        if not raw:
            continue
        await record_capture_memory(
            raw_text=raw,
            source="backfill",
            source_agent=entry.source_agent or (item.source_agent if item else None),
            source_session_id=entry.source_session_id,
            entry=entry,
            life_item=item,
            event_type="backfill_open_item",
        )
        count += 1
    return count


async def _backfill_recent_user_turns(days: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    count = 0
    async with async_session() as db:
        result = await db.execute(
            select(MemoryEntry)
            .where(MemoryEntry.role == "user")
            .where(MemoryEntry.timestamp >= since.replace(tzinfo=None))
            .order_by(MemoryEntry.timestamp.desc(), MemoryEntry.id.desc())
            .limit(500)
        )
        rows = list(result.scalars().all())
    for row in rows:
        await record_memory_event(
            raw_text=row.content,
            source="backfill",
            source_agent=row.agent_name,
            source_session_id=row.session_id,
            event_type="backfill_user_turn",
            title=row.content[:120] or "Backfilled user turn",
            tags=["backfill", "chat"],
        )
        count += 1
    return count


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recent-days", type=int, default=14)
    args = parser.parse_args()
    await init_db()
    open_count = await _backfill_open_items()
    turn_count = await _backfill_recent_user_turns(args.recent_days)
    print(f"Backfilled memory ledger: open_items={open_count} recent_user_turns={turn_count}")


if __name__ == "__main__":
    asyncio.run(main())
