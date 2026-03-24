"""Server-Sent Events router for realtime Mission Control updates."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.database import async_session
from app.config import settings
from app.security import require_api_token
from app.services.events import (
    SSE_AUTH_COOKIE,
    build_event,
    event_broadcaster,
    sse_auth_sessions,
)

router = APIRouter()


def _encode_sse(payload: dict) -> str:
    data = json.dumps(payload, separators=(",", ":"))
    return f"id: {payload['id']}\ndata: {data}\n\n"


async def _readiness_snapshot() -> dict:
    db_ok = False
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ready" if db_ok else "degraded", "database": db_ok}


@router.post("/auth", dependencies=[Depends(require_api_token)])
async def issue_events_session(response: Response):
    # EventSource cannot send custom auth headers; exchange the token for a short-lived
    # same-origin HttpOnly cookie dedicated to /api/events streaming.
    session_token, max_age = await sse_auth_sessions.issue()
    response.set_cookie(
        key=SSE_AUTH_COOKIE,
        value=session_token,
        httponly=True,
        samesite="strict",
        secure=not settings.local_mode,
        max_age=max_age,
        path="/api/events",
    )
    return {"ok": True}


@router.get("")
async def stream_events(
    request: Request,
    lifeos_sse_session: str | None = Cookie(default=None, alias=SSE_AUTH_COOKIE),
):
    if not await sse_auth_sessions.validate(lifeos_sse_session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid SSE session")

    async def event_generator():
        subscriber_id, queue = await event_broadcaster.subscribe()
        last_system_emit = 0.0
        try:
            while True:
                if await request.is_disconnected():
                    break

                now = asyncio.get_running_loop().time()
                if now - last_system_emit >= 30:
                    health_event = build_event(
                        "system.health.updated",
                        {"kind": "system", "id": "health"},
                        {"status": "healthy", "service": "lifeos-backend", "version": "1-5"},
                    )
                    readiness_event = build_event(
                        "system.readiness.updated",
                        {"kind": "system", "id": "readiness"},
                        await _readiness_snapshot(),
                    )
                    last_system_emit = now
                    yield _encode_sse(health_event)
                    yield _encode_sse(readiness_event)

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _encode_sse(event)
                except asyncio.TimeoutError:
                    yield f": keepalive {datetime.now(timezone.utc).isoformat()}\n\n"
        finally:
            await event_broadcaster.unsubscribe(subscriber_id)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)
