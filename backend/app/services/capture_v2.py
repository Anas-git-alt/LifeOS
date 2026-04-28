"""Compatibility wrappers for agentic capture planning."""

from __future__ import annotations

from typing import Any

from app.models import CaptureItemResponse, RawCapture
from app.services.capture_agentic import create_raw_capture, split_capture_message, update_raw_capture


async def create_raw_capture_event(
    *,
    message: str,
    source: str,
    source_session_id: int | None,
    source_message_id: str | None = None,
    source_channel_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RawCapture:
    return await create_raw_capture(
        message=message,
        source=source,
        session_id=source_session_id,
        source_message_id=source_message_id,
        source_channel_id=source_channel_id,
        metadata=metadata,
    )


async def update_raw_capture_event(
    raw_capture_id: int,
    *,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> RawCapture | None:
    return await update_raw_capture(raw_capture_id, status=status, metadata=metadata)


__all__ = [
    "CaptureItemResponse",
    "RawCapture",
    "create_raw_capture_event",
    "split_capture_message",
    "update_raw_capture_event",
]
