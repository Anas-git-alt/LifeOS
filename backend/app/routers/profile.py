"""Profile router."""

from fastapi import APIRouter, Depends

from app.models import ProfileResponse, ProfileUpdate
from app.security import require_api_token
from app.services.profile import get_or_create_profile, update_profile

router = APIRouter()


@router.get("/", response_model=ProfileResponse, dependencies=[Depends(require_api_token)])
async def get_profile():
    profile = await get_or_create_profile()
    return ProfileResponse.model_validate(profile)


@router.put("/", response_model=ProfileResponse, dependencies=[Depends(require_api_token)])
async def put_profile(data: ProfileUpdate):
    profile = await update_profile(data)
    return ProfileResponse.model_validate(profile)
