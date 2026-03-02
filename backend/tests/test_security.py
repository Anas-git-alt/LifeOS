"""Security dependency tests."""

import pytest
from fastapi import HTTPException

from app.config import settings
from app.security import require_api_token


@pytest.mark.asyncio
async def test_require_api_token_accepts_valid():
    await require_api_token(settings.api_secret_key)


@pytest.mark.asyncio
async def test_require_api_token_rejects_missing():
    with pytest.raises(HTTPException) as exc:
        await require_api_token(None)
    assert exc.value.status_code == 401
