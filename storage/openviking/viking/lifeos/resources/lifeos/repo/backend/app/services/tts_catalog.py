"""Static local TTS catalog and DB sync utilities."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import TTSModelRegistry


TTS_CATALOG: list[dict[str, Any]] = [
    {
        "engine": "chatterbox_turbo",
        "model_id": "chatterbox-turbo",
        "display_name": "Chatterbox Turbo",
        "supports_languages": ["en", "fr", "ar"],
        "supports_voice_id": True,
        "supports_voice_instructions": True,
        "supports_reference_audio": False,
        "supports_emotion_control": True,
        "supports_streaming": True,
        "quality_tier": "balanced",
        "latency_tier": "very_fast",
        "vram_estimate_mb": 3200,
        "license_label": "Check upstream model card",
        "enabled": True,
    },
    {
        "engine": "xtts_v2",
        "model_id": "xtts-v2",
        "display_name": "Coqui XTTS v2",
        "supports_languages": ["en", "fr", "ar"],
        "supports_voice_id": True,
        "supports_voice_instructions": True,
        "supports_reference_audio": True,
        "supports_emotion_control": True,
        "supports_streaming": False,
        "quality_tier": "high",
        "latency_tier": "medium",
        "vram_estimate_mb": 5200,
        "license_label": "Check Coqui license terms",
        "enabled": True,
    },
    {
        "engine": "qwen3_tts",
        "model_id": "qwen3-tts",
        "display_name": "Qwen3 TTS (Experimental)",
        "supports_languages": ["en", "fr"],
        "supports_voice_id": True,
        "supports_voice_instructions": True,
        "supports_reference_audio": False,
        "supports_emotion_control": True,
        "supports_streaming": True,
        "quality_tier": "high",
        "latency_tier": "medium",
        "vram_estimate_mb": 6500,
        "license_label": "Check upstream model card",
        "enabled": False,
    },
]


def _supports_lang(model: dict[str, Any], lang: str) -> bool:
    return lang in set(model.get("supports_languages", []))


async def sync_tts_registry() -> None:
    """Upsert static catalog into DB to drive capability-aware UX."""
    async with async_session() as db:
        for entry in TTS_CATALOG:
            result = await db.execute(
                select(TTSModelRegistry).where(
                    TTSModelRegistry.engine == entry["engine"],
                    TTSModelRegistry.model_id == entry["model_id"],
                )
            )
            row = result.scalar_one_or_none()
            payload = dict(
                display_name=entry["display_name"],
                supports_en=_supports_lang(entry, "en"),
                supports_fr=_supports_lang(entry, "fr"),
                supports_ar=_supports_lang(entry, "ar"),
                supports_voice_id=entry["supports_voice_id"],
                supports_voice_instructions=entry["supports_voice_instructions"],
                supports_reference_audio=entry["supports_reference_audio"],
                supports_emotion_control=entry["supports_emotion_control"],
                supports_streaming=entry["supports_streaming"],
                quality_tier=entry["quality_tier"],
                latency_tier=entry["latency_tier"],
                vram_estimate_mb=entry["vram_estimate_mb"],
                license_label=entry["license_label"],
                enabled=entry["enabled"],
                config_json={},
            )
            if row:
                for key, value in payload.items():
                    setattr(row, key, value)
                continue
            db.add(
                TTSModelRegistry(
                    engine=entry["engine"],
                    model_id=entry["model_id"],
                    **payload,
                )
            )
        await db.commit()
