"""Local TTS worker with adapter abstraction and one-warm-model policy."""

from __future__ import annotations

import base64
import os
import subprocess
import time
import tempfile
from dataclasses import dataclass
from typing import Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


SAMPLE_RATE = 24000
PIPER_MODEL_DIR = "/models/piper"


class SynthesizeRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    engine: str
    model_id: str
    text: str
    voice_id: str | None = None
    language: str = "en"
    voice_instructions: str | None = None
    voice_params: dict = Field(default_factory=dict)
    reference_audio_path: str | None = None
    queue_policy: str = "replace"


class SynthesizeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    engine: str
    model_id: str
    sample_rate_hz: int
    audio_b64_wav: str
    duration_ms: int
    cached: bool = False


class TTSEngine(Protocol):
    engine_name: str

    def warm(self, model_id: str) -> None:
        ...

    def synthesize(self, payload: SynthesizeRequest) -> bytes:
        ...


def _espeak_voice(language: str, voice_id: str | None) -> str:
    # Only pass explicit voice IDs to espeak if they look like espeak voices.
    # Piper model IDs like "en_US-lessac-high" are not valid espeak voices.
    if voice_id and "-" not in voice_id:
        return voice_id
    mapping = {
        "en": "en-us",
        "fr": "fr",
        "ar": "ar",
    }
    return mapping.get(language, "en-us")


def _piper_model_path(language: str, voice_id: str | None) -> tuple[str, str] | None:
    candidates: list[str] = []
    if voice_id:
        candidates.append(f"en/{voice_id}.onnx")
    if language == "en":
        candidates.extend(
            [
                "en/en_US-lessac-high.onnx",
                "en/en_US-lessac-medium.onnx",
            ]
        )
    for model_rel in candidates:
        onnx_path = os.path.join(PIPER_MODEL_DIR, model_rel)
        json_path = f"{onnx_path}.json"
        if os.path.exists(onnx_path) and os.path.exists(json_path):
            return onnx_path, json_path
    return None


def _synthesize_with_piper(text: str, *, language: str, voice_id: str | None, speed: float) -> bytes:
    model_paths = _piper_model_path(language, voice_id)
    if not model_paths:
        raise FileNotFoundError(f"No piper model available for language '{language}'")
    onnx_path, json_path = model_paths
    length_scale = max(0.7, min(1.4, 1.0 / max(0.7, min(1.6, speed))))
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        completed = subprocess.run(
            [
                "piper",
                "--model",
                onnx_path,
                "--config",
                json_path,
                "--output_file",
                wav_path,
                "--length_scale",
                str(length_scale),
            ],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "piper failed").strip())
        with open(wav_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


def _synthesize_with_espeak(
    text: str,
    *,
    language: str,
    voice_id: str | None,
    speed: float,
    pitch: float,
) -> bytes:
    # espeak speed range is roughly 80..450 wpm, pitch range 0..99.
    espeak_speed = max(80, min(450, int(170 * max(0.6, min(1.8, speed)))))
    espeak_pitch = max(0, min(99, int(50 + (pitch * 20))))
    voice = _espeak_voice(language, voice_id)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        completed = subprocess.run(
            [
                "espeak-ng",
                "-v",
                voice,
                "-s",
                str(espeak_speed),
                "-p",
                str(espeak_pitch),
                "-w",
                wav_path,
                text,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "espeak-ng failed").strip())
        with open(wav_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


class ChatterboxTurboAdapter:
    engine_name = "chatterbox_turbo"

    def __init__(self) -> None:
        self.warmed_model_id: str | None = None

    def warm(self, model_id: str) -> None:
        self.warmed_model_id = model_id

    def synthesize(self, payload: SynthesizeRequest) -> bytes:
        params = payload.voice_params or {}
        speed = float(params.get("speed", 1.1))
        emotion = float(params.get("emotion_intensity", 0.6))
        try:
            return _synthesize_with_piper(
                payload.text,
                language=payload.language,
                voice_id=payload.voice_id,
                speed=speed,
            )
        except Exception:
            return _synthesize_with_espeak(
                payload.text,
                language=payload.language,
                voice_id=None,
                speed=speed,
                pitch=emotion,
            )


class XTTSV2Adapter:
    engine_name = "xtts_v2"

    def __init__(self) -> None:
        self.warmed_model_id: str | None = None

    def warm(self, model_id: str) -> None:
        self.warmed_model_id = model_id

    def synthesize(self, payload: SynthesizeRequest) -> bytes:
        params = payload.voice_params or {}
        speed = float(params.get("speed", 0.9))
        stability = float(params.get("stability", 0.8))
        try:
            return _synthesize_with_piper(
                payload.text,
                language=payload.language,
                voice_id=payload.voice_id,
                speed=speed,
            )
        except Exception:
            return _synthesize_with_espeak(
                payload.text,
                language=payload.language,
                voice_id=None,
                speed=speed,
                pitch=stability,
            )


@dataclass
class WorkerState:
    warm_model_key: str | None = None
    active_request_id: str | None = None
    interrupted_requests: set[str] | None = None


state = WorkerState(interrupted_requests=set())
adapters: dict[str, TTSEngine] = {
    "chatterbox_turbo": ChatterboxTurboAdapter(),
    "xtts_v2": XTTSV2Adapter(),
}

app = FastAPI(title="LifeOS TTS Worker", version="1-5")


def _resolve_adapter(engine: str) -> TTSEngine:
    adapter = adapters.get(engine)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unsupported TTS engine '{engine}'")
    return adapter


def _warm_one_model(adapter: TTSEngine, engine: str, model_id: str) -> None:
    # Single warm model policy: track one active warm key globally.
    adapter.warm(model_id)
    state.warm_model_key = f"{engine}:{model_id}"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "warm_model_key": state.warm_model_key,
        "active_request_id": state.active_request_id,
    }


@app.post("/interrupt/{request_id}")
def interrupt(request_id: str):
    state.interrupted_requests.add(request_id)
    if state.active_request_id == request_id:
        state.active_request_id = None
    return {"status": "interrupted", "request_id": request_id}


@app.post("/synthesize", response_model=SynthesizeResponse)
def synthesize(data: SynthesizeRequest):
    if not data.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")
    adapter = _resolve_adapter(data.engine)
    _warm_one_model(adapter, data.engine, data.model_id)
    if data.request_id in state.interrupted_requests:
        raise HTTPException(status_code=409, detail="Request interrupted")

    state.active_request_id = data.request_id
    started = time.perf_counter()
    try:
        audio_wav = adapter.synthesize(data)
    except Exception as exc:
        state.active_request_id = None
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {exc}") from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    if data.request_id in state.interrupted_requests:
        state.active_request_id = None
        raise HTTPException(status_code=409, detail="Request interrupted")
    state.active_request_id = None
    encoded = base64.b64encode(audio_wav).decode("ascii")
    return SynthesizeResponse(
        request_id=data.request_id,
        engine=data.engine,
        model_id=data.model_id,
        sample_rate_hz=SAMPLE_RATE,
        audio_b64_wav=encoded,
        duration_ms=duration_ms,
        cached=False,
    )
