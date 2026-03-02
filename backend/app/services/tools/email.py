"""Email Tool — stub for future integration."""

import logging

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email. Stub — returns mock confirmation."""
    return {
        "status": "stub",
        "message": f"Would send email to '{to}': {subject}",
        "note": "Email integration not yet configured. Add SMTP or Gmail API credentials."
    }


async def check_inbox(limit: int = 5) -> list[dict]:
    """Check email inbox. Stub — returns empty list."""
    logger.info("Email stub called — returning empty inbox")
    return []
