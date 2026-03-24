"""TTS API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import (
    Agent,
    TTSHealthResponse,
    TTSModelCapabilityResponse,
    TTSModelRegistry,
    TTSPreviewRequest,
    TTSPayload,
    TTSSynthesizeResponse,
)
from app.security import require_api_token
from app.services.tts_manager import tts_manager

router = APIRouter()


def _supports_language(model: TTSModelRegistry, language: str) -> bool:
    if language == "en":
        return model.supports_en
    if language == "fr":
        return model.supports_fr
    if language == "ar":
        return model.supports_ar
    return False


def _normalize_model_language(agent: Agent, requested: str | None) -> str:
    return requested or agent.default_language or "en"


async def _resolve_agent_with_model(agent_name: str) -> tuple[Agent, TTSModelRegistry]:
    async with async_session() as db:
        agent_result = await db.execute(select(Agent).where(Agent.name == agent_name))
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        if not agent.speech_enabled:
            raise HTTPException(status_code=400, detail=f"Speech is disabled for agent '{agent_name}'")
        engine = agent.tts_engine or settings.tts_default_engine
        model_id = agent.tts_model_id or settings.tts_default_model_id
        model_result = await db.execute(
            select(TTSModelRegistry).where(
                TTSModelRegistry.engine == engine,
                TTSModelRegistry.model_id == model_id,
                TTSModelRegistry.enabled.is_(True),
            )
        )
        model = model_result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=400, detail=f"TTS model '{engine}:{model_id}' is unavailable")
        return agent, model


@router.get("/models", response_model=list[TTSModelCapabilityResponse], dependencies=[Depends(require_api_token)])
async def list_tts_models():
    async with async_session() as db:
        result = await db.execute(
            select(TTSModelRegistry).where(TTSModelRegistry.enabled.is_(True)).order_by(TTSModelRegistry.id)
        )
        rows = result.scalars().all()
        output: list[TTSModelCapabilityResponse] = []
        for row in rows:
            supports_languages = []
            if row.supports_en:
                supports_languages.append("en")
            if row.supports_fr:
                supports_languages.append("fr")
            if row.supports_ar:
                supports_languages.append("ar")
            output.append(
                TTSModelCapabilityResponse(
                    engine=row.engine,
                    model_id=row.model_id,
                    display_name=row.display_name,
                    supports_languages=supports_languages,
                    supports_voice_id=row.supports_voice_id,
                    supports_voice_instructions=row.supports_voice_instructions,
                    supports_reference_audio=row.supports_reference_audio,
                    supports_emotion_control=row.supports_emotion_control,
                    supports_streaming=row.supports_streaming,
                    quality_tier=row.quality_tier,
                    latency_tier=row.latency_tier,
                    vram_estimate_mb=row.vram_estimate_mb,
                    license_label=row.license_label,
                    enabled=row.enabled,
                )
            )
        return output


@router.post("/preview", response_model=TTSSynthesizeResponse, dependencies=[Depends(require_api_token)])
async def preview_tts(data: TTSPreviewRequest):
    agent, model = await _resolve_agent_with_model(data.agent_name)
    text = (data.text or agent.preview_text or "Assalamu Alaikum. This is a voice preview.").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Preview text is required")
    language = _normalize_model_language(agent, data.language)
    if not _supports_language(model, language):
        raise HTTPException(status_code=400, detail=f"Model does not support language '{language}'")
    payload = await tts_manager.synthesize(
        agent_name=agent.name,
        text=text,
        engine=model.engine,
        model_id=model.model_id,
        voice_id=agent.voice_id,
        language=language,
        voice_instructions=agent.voice_instructions,
        voice_params=agent.voice_params_json,
        reference_audio_path=agent.reference_audio_path,
        queue_policy="append",
    )
    return TTSSynthesizeResponse.model_validate(payload)


@router.post("/synthesize", response_model=TTSSynthesizeResponse, dependencies=[Depends(require_api_token)])
async def synthesize_tts(data: TTSPayload):
    agent, model = await _resolve_agent_with_model(data.agent_name)
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")
    language = _normalize_model_language(agent, data.language)
    if not _supports_language(model, language):
        raise HTTPException(status_code=400, detail=f"Model does not support language '{language}'")

    merged_params = dict(agent.voice_params_json or {})
    if data.runtime_overrides:
        merged_params.update(data.runtime_overrides)

    payload = await tts_manager.synthesize(
        agent_name=agent.name,
        text=text,
        engine=model.engine,
        model_id=model.model_id,
        voice_id=agent.voice_id,
        language=language,
        voice_instructions=agent.voice_instructions,
        voice_params=merged_params,
        reference_audio_path=agent.reference_audio_path,
        queue_policy=data.queue_policy,
    )
    return TTSSynthesizeResponse.model_validate(payload)


@router.get("/health", response_model=TTSHealthResponse, dependencies=[Depends(require_api_token)])
async def tts_health():
    payload = await tts_manager.health()
    return TTSHealthResponse.model_validate(payload)
