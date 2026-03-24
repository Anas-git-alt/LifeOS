"""API security helpers for token-based owner access."""

from fastapi import Header, HTTPException, status

from app.config import settings


def _is_valid_token(token: str | None) -> bool:
    if not token or not settings.api_secret_key:
        return False
    return token == settings.api_secret_key


async def require_api_token(x_lifeos_token: str | None = Header(default=None)) -> None:
    """Require X-LifeOS-Token on protected endpoints."""
    if not _is_valid_token(x_lifeos_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-LifeOS-Token",
        )
