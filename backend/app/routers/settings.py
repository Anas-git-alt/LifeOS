"""Global system settings router."""

from fastapi import APIRouter, Depends

from app.models import SystemSettingsResponse, SystemSettingsUpdate
from app.security import require_api_token
from app.services.system_settings import get_or_create_system_settings, update_system_settings

router = APIRouter()


@router.get("/", response_model=SystemSettingsResponse, dependencies=[Depends(require_api_token)])
async def get_settings():
    row = await get_or_create_system_settings()
    return SystemSettingsResponse(
        id=row.id,
        data_start_date=row.data_start_date.strftime("%Y-%m-%d"),
        default_timezone=row.default_timezone,
        autonomy_enabled=row.autonomy_enabled,
        approval_required_for_mutations=row.approval_required_for_mutations,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/", response_model=SystemSettingsResponse, dependencies=[Depends(require_api_token)])
async def put_settings(data: SystemSettingsUpdate):
    row = await update_system_settings(data)
    return SystemSettingsResponse(
        id=row.id,
        data_start_date=row.data_start_date.strftime("%Y-%m-%d"),
        default_timezone=row.default_timezone,
        autonomy_enabled=row.autonomy_enabled,
        approval_required_for_mutations=row.approval_required_for_mutations,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
