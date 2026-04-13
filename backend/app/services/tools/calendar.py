"""Calendar Tool — stub for future integration."""

import logging

logger = logging.getLogger(__name__)


async def get_today_events() -> list[dict]:
    """Get today's calendar events. Stub — integrate with Google Calendar API later."""
    logger.info("Calendar stub called — returning empty events")
    return []


async def add_event(title: str, date: str, time: str = "", notes: str = "") -> dict:
    """Add a calendar event. Stub — returns mock confirmation."""
    return {
        "status": "stub",
        "message": f"Would add event: '{title}' on {date} {time}",
        "note": "Calendar integration not yet configured. Add Google Calendar API credentials."
    }
