"""Shadow-router free-mode safeguards."""

from unittest.mock import AsyncMock

import pytest

from app.services.shadow_router import _pick_shadow_provider, maybe_shadow_test


def test_pick_shadow_provider_skips_paid_providers_in_free_mode(monkeypatch):
    monkeypatch.setattr("app.services.provider_router.settings.free_only_mode", True)
    monkeypatch.setattr("app.services.provider_router.settings.nvidia_nim_free_tier_allowed", True)
    monkeypatch.setattr("app.services.provider_router.settings.nvidia_api_key", "nim-key")
    monkeypatch.setattr("app.services.provider_router.settings.openai_api_key", "openai-key")
    monkeypatch.setattr("app.services.provider_router.settings.openai_default_model", "gpt-4o-mini")
    monkeypatch.setattr("app.services.provider_router.telemetry.is_circuit_open", lambda _name: False)

    assert _pick_shadow_provider("openrouter") == ("nvidia", "meta/llama-3.1-8b-instruct")


@pytest.mark.asyncio
async def test_shadow_router_disabled_by_default_does_not_run_background_call(monkeypatch):
    run_shadow_call = AsyncMock()
    monkeypatch.setattr("app.services.shadow_router.settings.shadow_router_enabled", False)
    monkeypatch.setattr("app.services.shadow_router._run_shadow_call", run_shadow_call)

    await maybe_shadow_test(
        messages=[{"role": "user", "content": "hello"}],
        primary_result="hi",
        primary_provider="openrouter",
        primary_model="openrouter/free",
    )

    run_shadow_call.assert_not_awaited()
