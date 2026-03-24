"""Realtime event broadcasting and SSE auth sessions."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

logger = logging.getLogger("lifeos.events")

SSE_AUTH_COOKIE = "lifeos_sse_session"
SSE_AUTH_TTL_SECONDS = 8 * 60 * 60


def build_event(event_type: str, entity: dict, payload: dict | None = None) -> dict:
    """Create a standard LifeOS realtime event envelope."""
    return {
        "id": f"evt_{uuid4().hex}",
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        "entity": entity,
        "payload": payload or {},
    }


class EventBroadcaster:
    def __init__(self, queue_size: int = 256):
        self._queue_size = queue_size
        self._subscribers: dict[str, asyncio.Queue[dict]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self) -> tuple[str, asyncio.Queue[dict]]:
        subscriber_id = uuid4().hex
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers[subscriber_id] = queue
        return subscriber_id, queue

    async def unsubscribe(self, subscriber_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(subscriber_id, None)

    async def publish(self, event_type: str, entity: dict, payload: dict | None = None) -> dict:
        event = build_event(event_type, entity, payload)
        async with self._lock:
            queues = list(self._subscribers.values())

        for queue in queues:
            if queue.full():
                # Drop oldest to keep stream moving under bursty writes.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                logger.warning("sse_queue_overflow dropping_oldest")
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("sse_queue_overflow_drop_failed")
        return event


class SseAuthSessions:
    """Ephemeral SSE cookie sessions created from existing API token auth."""

    def __init__(self, ttl_seconds: int = SSE_AUTH_TTL_SECONDS):
        self._ttl = timedelta(seconds=ttl_seconds)
        self._sessions: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, expires_at: datetime) -> bool:
        return datetime.now(timezone.utc) >= expires_at

    async def issue(self) -> tuple[str, int]:
        token = f"sse_{uuid4().hex}"
        expires_at = datetime.now(timezone.utc) + self._ttl
        async with self._lock:
            self._sessions[token] = expires_at
            self._cleanup_locked()
        return token, int(self._ttl.total_seconds())

    async def validate(self, token: str | None) -> bool:
        if not token:
            return False
        async with self._lock:
            expires_at = self._sessions.get(token)
            if not expires_at:
                return False
            if self._is_expired(expires_at):
                self._sessions.pop(token, None)
                return False
            return True

    async def revoke(self, token: str | None) -> None:
        if not token:
            return
        async with self._lock:
            self._sessions.pop(token, None)

    def _cleanup_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [token for token, expires_at in self._sessions.items() if expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)


event_broadcaster = EventBroadcaster()
sse_auth_sessions = SseAuthSessions()


async def publish_event(event_type: str, entity: dict, payload: dict | None = None) -> dict:
    return await event_broadcaster.publish(event_type, entity, payload)
