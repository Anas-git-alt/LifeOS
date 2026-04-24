"""Tests for the provider router."""

import pytest
from app.services.provider_router import PROVIDERS, free_mode_rejection, get_available_providers


def test_provider_configs_exist():
    """All 4 providers should be configured."""
    assert "openrouter" in PROVIDERS
    assert "nvidia" in PROVIDERS
    assert "google" in PROVIDERS
    assert "openai" in PROVIDERS


def test_provider_urls():
    """Each provider should have a valid base URL."""
    for name, config in PROVIDERS.items():
        assert config["base_url"].startswith("https://"), f"{name} missing HTTPS URL"
        assert config["api_key_attr"], f"{name} missing api_key_attr"
        assert config["default_model_attr"], f"{name} missing default_model_attr"


def test_get_available_providers(monkeypatch):
    """Should return list of dicts with name, available, base_url, default_model."""
    monkeypatch.setattr("app.services.provider_router.settings.openrouter_api_key", "or-key")
    monkeypatch.setattr("app.services.provider_router.settings.openrouter_default_model", "openrouter/free")
    monkeypatch.setattr("app.services.provider_router.settings.openai_api_key", "oa-key")
    monkeypatch.setattr("app.services.provider_router.settings.free_only_mode", True)

    result = get_available_providers()
    assert isinstance(result, list)
    assert len(result) == 4
    for p in result:
        assert "name" in p
        assert "available" in p
        assert "base_url" in p
        assert "default_model" in p
        assert "free_mode_allowed" in p
        assert "free_mode_reason" in p

    by_name = {p["name"]: p for p in result}
    assert by_name["openrouter"]["free_mode_allowed"] is True
    assert by_name["openai"]["free_mode_allowed"] is False
    assert by_name["openai"]["free_mode_reason"] == "free_only_mode blocks provider `openai`"


@pytest.mark.parametrize(
    ("provider", "model", "blocked"),
    [
        ("openrouter", "openrouter/free", False),
        ("openrouter", "deepseek/deepseek-chat-v3-0324:free", False),
        ("openrouter", "openrouter/auto", True),
        ("nvidia", "meta/llama-3.1-8b-instruct", False),
        ("google", "gemini-2.0-flash", True),
        ("openai", "gpt-4o-mini", True),
    ],
)
def test_free_only_mode_allows_only_free_provider_paths(monkeypatch, provider, model, blocked):
    monkeypatch.setattr("app.services.provider_router.settings.free_only_mode", True)
    monkeypatch.setattr("app.services.provider_router.settings.nvidia_nim_free_tier_allowed", True)

    reason = free_mode_rejection(provider, model)

    assert (reason is not None) is blocked


def test_free_only_mode_can_be_disabled(monkeypatch):
    monkeypatch.setattr("app.services.provider_router.settings.free_only_mode", False)

    assert free_mode_rejection("openai", "gpt-4o-mini") is None
