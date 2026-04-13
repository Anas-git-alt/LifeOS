"""Tests for the provider router."""

import pytest
from app.services.provider_router import PROVIDERS, get_available_providers


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


def test_get_available_providers():
    """Should return list of dicts with name, available, base_url, default_model."""
    result = get_available_providers()
    assert isinstance(result, list)
    assert len(result) == 4
    for p in result:
        assert "name" in p
        assert "available" in p
        assert "base_url" in p
        assert "default_model" in p
