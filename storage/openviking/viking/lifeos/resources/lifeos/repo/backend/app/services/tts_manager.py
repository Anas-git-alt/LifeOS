"""TTS manager for worker delegation, caching, and interruption."""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.config import settings


@dataclass
class CacheEntry:
    audio_b64_wav: str
    duration_ms: int
    created_at: float


class TTSManager:
    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._active_request_id: Optional[str] = None
        self._queue_depth: int = 0
        self._warm_model_key: Optional[str] = None

    @staticmethod
    def _cache_key(
        agent_name: str,
        text: str,
        model_id: str,
        voice_id: str | None,
        language: str,
        voice_params: dict[str, Any] | None,
    ) -> str:
        joined = "|".join(
            [
                agent_name,
                model_id,
                voice_id or "",
                language,
                text.strip(),
                str(voice_params or {}),
            ]
        )
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def _purge_expired(self) -> None:
        ttl = max(1, int(settings.tts_cache_ttl_seconds))
        now = time.time()
        stale = [key for key, value in self._cache.items() if now - value.created_at > ttl]
        for key in stale:
            self._cache.pop(key, None)

    async def _post(self, path: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{settings.tts_worker_url}{path}", json=payload)
            response.raise_for_status()
            return response.json()

    async def _get(self, path: str, timeout_seconds: float) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(f"{settings.tts_worker_url}{path}")
            response.raise_for_status()
            return response.json()

    async def synthesize(
        self,
        *,
        agent_name: str,
        text: str,
        engine: str,
        model_id: str,
        voice_id: str | None,
        language: str,
        voice_instructions: str | None,
        voice_params: dict[str, Any] | None,
        reference_audio_path: str | None,
        queue_policy: str = "replace",
    ) -> dict[str, Any]:
        self._purge_expired()
        request_id = str(uuid.uuid4())
        cache_key = self._cache_key(agent_name, text, model_id, voice_id, language, voice_params)
        if settings.tts_enable_cache and queue_policy == "append":
            cached = self._cache.get(cache_key)
            if cached:
                return {
                    "request_id": request_id,
                    "engine": engine,
                    "model_id": model_id,
                    "sample_rate_hz": 24000,
                    "audio_b64_wav": cached.audio_b64_wav,
                    "cached": True,
                    "duration_ms": cached.duration_ms,
                }

        self._active_request_id = request_id
        self._queue_depth += 1
        try:
            payload = await self._post(
                "/synthesize",
                {
                    "request_id": request_id,
                    "engine": engine,
                    "model_id": model_id,
                    "text": text,
                    "voice_id": voice_id,
                    "language": language,
                    "voice_instructions": voice_instructions,
                    "voice_params": voice_params or {},
                    "reference_audio_path": reference_audio_path,
                    "queue_policy": queue_policy,
                },
                timeout_seconds=settings.tts_request_timeout_seconds,
            )
            self._warm_model_key = f"{engine}:{model_id}"
            if settings.tts_enable_cache and queue_policy == "append":
                self._cache[cache_key] = CacheEntry(
                    audio_b64_wav=payload["audio_b64_wav"],
                    duration_ms=int(payload.get("duration_ms", 0)),
                    created_at=time.time(),
                )
            return payload
        finally:
            self._queue_depth = max(0, self._queue_depth - 1)

    async def interrupt(self, request_id: str | None = None) -> dict[str, Any]:
        target_request = request_id or self._active_request_id
        if not target_request:
            return {"status": "idle"}
        payload = await self._post(
            f"/interrupt/{target_request}",
            {},
            timeout_seconds=settings.tts_health_timeout_seconds,
        )
        self._active_request_id = None
        return payload

    async def health(self) -> dict[str, Any]:
        self._purge_expired()
        worker = await self._get("/health", timeout_seconds=settings.tts_health_timeout_seconds)
        if worker.get("warm_model_key"):
            self._warm_model_key = worker["warm_model_key"]
        return {
            "status": worker.get("status", "unknown"),
            "warm_model_key": self._warm_model_key,
            "queue_depth": self._queue_depth,
            "active_request_id": self._active_request_id,
            "cache_entries": len(self._cache),
            "policy": {
                "single_active_global_session": True,
                "one_warm_model": True,
                "cache_enabled": bool(settings.tts_enable_cache),
                "cache_ttl_seconds": int(settings.tts_cache_ttl_seconds),
            },
        }


tts_manager = TTSManager()
