"""Multi-provider LLM router with retry, fallback, circuit breaker, and telemetry."""

import asyncio
import logging
import time
from typing import Optional

import httpx

from app.config import settings
from app.services import telemetry

logger = logging.getLogger(__name__)

PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_attr": "openrouter_api_key",
        "default_model_attr": "openrouter_default_model",
        "headers_extra": {
            "HTTP-Referer": "https://lifeos.local",
            "X-Title": "LifeOS Agent",
        },
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_attr": "nvidia_api_key",
        "default_model_attr": "nvidia_default_model",
        "headers_extra": {},
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_attr": "google_api_key",
        "default_model_attr": "google_default_model",
        "headers_extra": {},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_attr": "openai_api_key",
        "default_model_attr": "openai_default_model",
        "headers_extra": {},
    },
}

# Shared AsyncClient instances — one per provider — so TCP connections are
# reused across requests. Timeout is set at the client level.
_http_clients: dict[str, httpx.AsyncClient] = {}


def _get_client(provider: str) -> httpx.AsyncClient:
    """Return (or lazily create) the shared httpx client for a provider."""
    if provider not in _http_clients:
        _http_clients[provider] = httpx.AsyncClient(timeout=45.0)
    return _http_clients[provider]


async def close_all_clients() -> None:
    """Close all provider HTTP clients. Call this during application shutdown."""
    for client in _http_clients.values():
        await client.aclose()
    _http_clients.clear()


class LLMProvidersExhaustedError(RuntimeError):
    """Raised when all configured providers fail."""

    def __init__(self, failures: list[str]):
        self.failures = failures
        super().__init__(f"All LLM providers failed ({', '.join(failures)}).")


def _summarize_failure(provider: str, exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"{provider}:timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{provider}:http_{exc.response.status_code}"
    if isinstance(exc, ValueError):
        return f"{provider}:config"
    return f"{provider}:error"


async def chat_completion(
    messages: list[dict],
    provider: str = "openrouter",
    model: Optional[str] = None,
    fallback_provider: Optional[str] = None,
    fallback_model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    failures: list[str] = []

    # Skip circuit-open primary provider immediately to avoid latency penalty.
    if telemetry.is_circuit_open(provider):
        logger.warning("Circuit open for primary provider '%s', skipping.", provider)
        failures.append(f"{provider}:circuit_open")
    else:
        try:
            return await _call_provider(provider, model, messages, temperature, max_tokens)
        except Exception as exc:
            failures.append(_summarize_failure(provider, exc))
            logger.warning("Primary provider failed: %s", failures[-1])

    if fallback_provider:
        if telemetry.is_circuit_open(fallback_provider):
            logger.warning("Circuit open for fallback provider '%s', skipping.", fallback_provider)
            failures.append(f"{fallback_provider}:circuit_open")
        else:
            try:
                return await _call_provider(fallback_provider, fallback_model, messages, temperature, max_tokens)
            except Exception as exc:
                failures.append(_summarize_failure(fallback_provider, exc))
                logger.warning("Fallback provider failed: %s", failures[-1])

    for provider_name in PROVIDERS:
        if provider_name in (provider, fallback_provider):
            continue
        api_key = getattr(settings, PROVIDERS[provider_name]["api_key_attr"], "")
        if not api_key:
            continue
        if telemetry.is_circuit_open(provider_name):
            logger.debug("Circuit open for sweep provider '%s', skipping.", provider_name)
            failures.append(f"{provider_name}:circuit_open")
            continue
        try:
            return await _call_provider(provider_name, None, messages, temperature, max_tokens)
        except Exception as exc:
            failures.append(_summarize_failure(provider_name, exc))
            continue

    raise LLMProvidersExhaustedError(failures)


async def _call_provider(
    provider: str,
    model: Optional[str],
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    """Send a chat-completion request to a provider with exponential-backoff retry.

    Records latency and success/failure to the telemetry module after each attempt.
    """
    config = PROVIDERS.get(provider)
    if not config:
        raise ValueError(f"Unknown provider: {provider}")

    api_key = getattr(settings, config["api_key_attr"], "")
    if not api_key:
        raise ValueError(f"No API key configured for provider: {provider}")

    if not model:
        model = getattr(settings, config["default_model_attr"])

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **config.get("headers_extra", {}),
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    client = _get_client(provider)
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        t0 = time.monotonic()
        try:
            resp = await client.post(
                f"{config['base_url']}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if content is None:
                # Some models return null content on content-filter or tool-call responses.
                # Raise so the retry/fallback logic can try another provider.
                raise ValueError(f"{provider}: LLM returned null content (possible content filter)")
            latency_ms = (time.monotonic() - t0) * 1000
            tokens = data.get("usage", {}).get("total_tokens", 0)
            telemetry.record_call(provider, model, latency_ms, tokens, success=True)
            # Fire-and-forget shadow test — does NOT block this response.
            try:
                from app.services.shadow_router import maybe_shadow_test
                asyncio.create_task(
                    maybe_shadow_test(messages, content, provider, model)
                )
            except Exception:
                pass  # Shadow testing must never affect production flow
            return content
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            telemetry.record_call(provider, model, latency_ms, 0, success=False, error="timeout")
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            status_code = exc.response.status_code
            telemetry.record_call(provider, model, latency_ms, 0, success=False, error=f"http_{status_code}")
            last_exc = exc
            if status_code == 429:
                retry_after = exc.response.headers.get("Retry-After", "").strip()
                if retry_after.isdigit():
                    telemetry.record_rate_limit(provider, retry_after_seconds=int(retry_after))
                else:
                    telemetry.record_rate_limit(provider, retry_after_seconds=None)
            if 400 <= status_code < 500 and status_code != 429:
                raise
        if attempt < 3:
            delay = 2 ** (attempt - 1)
            if isinstance(last_exc, httpx.HTTPStatusError) and last_exc.response.status_code == 429:
                retry_after = last_exc.response.headers.get("Retry-After", "").strip()
                if retry_after.isdigit():
                    delay = max(delay, min(int(retry_after), 15))
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{provider} call failed without explicit exception")


def get_available_providers() -> list[dict]:
    result = []
    for name, config in PROVIDERS.items():
        api_key = getattr(settings, config["api_key_attr"], "")
        result.append(
            {
                "name": name,
                "available": bool(api_key),
                "base_url": config["base_url"],
                "default_model": getattr(settings, config["default_model_attr"]),
            }
        )
    return result
