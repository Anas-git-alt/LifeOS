"""Configuration parsing tests."""

from app.config import Settings


def test_owner_ids_parsing():
    settings = Settings(discord_owner_ids="123, 456,abc")
    assert settings.owner_ids == {123, 456}


def test_cors_origins_parsing():
    settings = Settings(cors_allow_origins="http://localhost:3000,http://127.0.0.1:3000")
    assert "http://localhost:3000" in settings.cors_origins
    assert "http://127.0.0.1:3000" in settings.cors_origins


def test_effective_openviking_api_key_falls_back_to_api_secret():
    settings = Settings(openviking_api_key="", api_secret_key="super-secret")
    assert settings.effective_openviking_api_key == "super-secret"
