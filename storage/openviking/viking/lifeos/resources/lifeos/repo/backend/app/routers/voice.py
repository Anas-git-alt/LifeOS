"""Voice session control routes."""

from fastapi import APIRouter, Depends

from app.models import (
    VoiceSessionInterruptRequest,
    VoiceSessionResponse,
    VoiceSessionStartRequest,
    VoiceSessionStopRequest,
)
from app.security import require_api_token
from app.services.tts_manager import tts_manager
from app.services.voice_sessions import interrupt_voice_session, start_voice_session, stop_voice_session

router = APIRouter()


@router.post("/start", response_model=VoiceSessionResponse, dependencies=[Depends(require_api_token)])
async def start_session(data: VoiceSessionStartRequest):
    row = await start_voice_session(
        guild_id=data.guild_id,
        channel_id=data.channel_id,
        agent_name=data.agent_name,
        queue_policy=data.queue_policy,
    )
    return VoiceSessionResponse(
        session_id=row.id,
        session_key=row.session_key,
        guild_id=row.guild_id,
        channel_id=row.channel_id,
        agent_name=row.agent_name,
        status=row.status,
        generation=row.generation,
        queue_policy=row.queue_policy,
    )


@router.post("/{session_id}/interrupt", response_model=VoiceSessionResponse, dependencies=[Depends(require_api_token)])
async def interrupt_session(session_id: int, data: VoiceSessionInterruptRequest):
    row = await interrupt_voice_session(session_id)
    await tts_manager.interrupt()
    return VoiceSessionResponse(
        session_id=row.id,
        session_key=row.session_key,
        guild_id=row.guild_id,
        channel_id=row.channel_id,
        agent_name=row.agent_name,
        status=row.status,
        generation=row.generation,
        queue_policy=row.queue_policy,
    )


@router.post("/{session_id}/stop", response_model=VoiceSessionResponse, dependencies=[Depends(require_api_token)])
async def stop_session(session_id: int, data: VoiceSessionStopRequest):
    row = await stop_voice_session(session_id)
    await tts_manager.interrupt()
    return VoiceSessionResponse(
        session_id=row.id,
        session_key=row.session_key,
        guild_id=row.guild_id,
        channel_id=row.channel_id,
        agent_name=row.agent_name,
        status=row.status,
        generation=row.generation,
        queue_policy=row.queue_policy,
    )
