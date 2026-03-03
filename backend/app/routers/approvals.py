"""Approval queue router."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.database import async_session
from app.models import ActionResponse, ActionStatus, ApprovalDecision, PendingAction
from app.security import require_api_token
from app.services.orchestrator import approve_action, reject_action

router = APIRouter()


@router.get("/", response_model=list[ActionResponse], dependencies=[Depends(require_api_token)])
async def list_pending():
    async with async_session() as db:
        result = await db.execute(
            select(PendingAction)
            .where(PendingAction.status == ActionStatus.PENDING)
            .order_by(PendingAction.created_at.desc())
        )
        return [ActionResponse.model_validate(action) for action in result.scalars().all()]


@router.get("/all", response_model=list[ActionResponse], dependencies=[Depends(require_api_token)])
async def list_all_actions():
    async with async_session() as db:
        result = await db.execute(select(PendingAction).order_by(PendingAction.created_at.desc()).limit(100))
        return [ActionResponse.model_validate(action) for action in result.scalars().all()]


@router.post("/decide", dependencies=[Depends(require_api_token)])
async def decide_action(decision: ApprovalDecision):
    if decision.approved:
        action = await approve_action(
            decision.action_id,
            reviewer=decision.reviewed_by,
            source=decision.source,
        )
    else:
        action = await reject_action(
            decision.action_id,
            reason=decision.reason or "",
            reviewer=decision.reviewed_by,
            source=decision.source,
        )
    if not action:
        raise HTTPException(status_code=404, detail="Action not found or already resolved")
    return {
        "id": action.id,
        "status": action.status.value,
        "message": f"Action {'approved' if decision.approved else 'rejected'}",
        "reviewed_by": action.reviewed_by,
        "review_source": action.review_source,
    }


@router.get("/stats", dependencies=[Depends(require_api_token)])
async def approval_stats():
    async with async_session() as db:
        result = await db.execute(
            select(PendingAction.status, func.count(PendingAction.id)).group_by(PendingAction.status)
        )
        counts = {
            (status.value if hasattr(status, "value") else str(status)).lower(): count
            for status, count in result.all()
        }
    return {
        "pending": counts.get("pending", 0),
        "approved": counts.get("approved", 0) + counts.get("executed", 0),
        "rejected": counts.get("rejected", 0),
        "executed": counts.get("executed", 0),
        "failed": counts.get("failed", 0),
    }
