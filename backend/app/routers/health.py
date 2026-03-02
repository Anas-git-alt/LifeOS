"""Health and readiness router."""

from fastapi import APIRouter
from sqlalchemy import text

from app.database import async_session

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "lifeos-backend", "version": "0.2.0"}


@router.get("/readiness")
async def readiness_check():
    db_ok = False
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ready" if db_ok else "degraded", "database": db_ok}
