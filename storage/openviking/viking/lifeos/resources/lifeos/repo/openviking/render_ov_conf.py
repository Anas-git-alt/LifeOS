"""Render an OpenViking ov.conf file from environment variables."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _embedding_api_key(provider: str, api_base: str, model: str) -> str:
    explicit = _env("OPENVIKING_EMBEDDING_API_KEY")
    if explicit:
        return explicit
    normalized = (provider or "").strip().lower()
    base = (api_base or "").strip().lower()
    model_name = (model or "").strip().lower()
    if normalized == "nvidia" or "integrate.api.nvidia.com" in base or model_name.startswith("nvidia/"):
        return _env("NVIDIA_API_KEY")
    if normalized == "openai":
        return _env("OPENAI_API_KEY")
    return _env("OPENAI_API_KEY") or _env("NVIDIA_API_KEY")


def _vlm_api_key(provider: str, api_base: str, model: str) -> str:
    explicit = _env("OPENVIKING_VLM_API_KEY")
    if explicit:
        return explicit
    normalized = (provider or "").strip().lower()
    base = (api_base or "").strip().lower()
    model_name = (model or "").strip().lower()
    if normalized == "nvidia" or "integrate.api.nvidia.com" in base or model_name.startswith("z-ai/"):
        return _env("NVIDIA_API_KEY")
    if normalized == "openai":
        return _env("OPENAI_API_KEY")
    return _env("OPENAI_API_KEY") or _env("NVIDIA_API_KEY")


def main() -> None:
    provider = _env("OPENVIKING_EMBEDDING_PROVIDER", "openai")
    api_base = _env("OPENVIKING_EMBEDDING_API_BASE", "https://api.openai.com/v1")
    model = _env("OPENVIKING_EMBEDDING_MODEL", "text-embedding-3-small")
    api_key = _embedding_api_key(provider, api_base, model)
    dimension = _env_int("OPENVIKING_EMBEDDING_DIMENSION", 1536)
    vlm_provider = _env("OPENVIKING_VLM_PROVIDER", "openai")
    vlm_api_base = _env("OPENVIKING_VLM_API_BASE", api_base)
    vlm_model = _env("OPENVIKING_VLM_MODEL", _env("NVIDIA_DEFAULT_MODEL", "z-ai/glm5"))
    vlm_api_key = _vlm_api_key(vlm_provider, vlm_api_base, vlm_model)
    root_api_key = _env("OPENVIKING_API_KEY") or _env("API_SECRET_KEY") or None
    if root_api_key == "change_me":
        root_api_key = None

    dense = {
        "provider": provider,
        "model": model,
        "dimension": dimension,
    }
    if api_key:
        dense["api_key"] = api_key
    if api_base:
        dense["api_base"] = api_base

    vlm = {
        "provider": vlm_provider,
        "model": vlm_model,
        "api_base": vlm_api_base,
    }
    if vlm_api_key:
        vlm["api_key"] = vlm_api_key

    config = {
        "server": {
            "host": "0.0.0.0",
            "port": 1933,
            "root_api_key": root_api_key,
            "cors_origins": ["*"],
        },
        "storage": {
            "workspace": "/app/data",
            "agfs": {"backend": "local"},
            "vectordb": {
                "backend": "local",
                "name": "context",
                "project": "lifeos",
            },
        },
        "embedding": {
            "dense": dense,
        },
        "vlm": vlm,
        "log": {
            "level": "INFO",
            "output": "stdout",
            "rotation": False,
        },
        "auto_generate_l0": True,
        "auto_generate_l1": True,
        "default_search_mode": "thinking",
        "default_search_limit": 4,
    }

    output_path = Path(_env("OPENVIKING_CONFIG_OUTPUT", "/app/ov.conf"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
