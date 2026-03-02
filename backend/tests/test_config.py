"""Configuration parsing tests."""

from app.config import Settings


def test_owner_ids_parsing():
    settings = Settings(discord_owner_ids="123, 456,abc")
    assert settings.owner_ids == {123, 456}


def test_cors_origins_parsing():
    settings = Settings(cors_allow_origins="http://localhost:3000,http://127.0.0.1:3000")
    assert "http://localhost:3000" in settings.cors_origins
    assert "http://127.0.0.1:3000" in settings.cors_origins
