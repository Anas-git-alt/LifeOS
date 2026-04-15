"""Experiment log service — persists shadow test results and detects promotion candidates."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session

logger = logging.getLogger(__name__)


async def log_run(
    primary_provider: str,
    primary_model: str,
    shadow_provider: str,
    shadow_model: str,
    primary_score: float,
    shadow_score: float,
    shadow_latency_ms: float,
    cost_estimate: float,
) -> None:
    """Persist a single shadow experiment run to the database."""
    try:
        from app.models import ExperimentRun
    except ImportError:
        logger.warning("ExperimentRun model not available — skipping experiment log.")
        return

    async with async_session() as db:
        run = ExperimentRun(
            primary_provider=primary_provider,
            primary_model=primary_model,
            shadow_provider=shadow_provider,
            shadow_model=shadow_model,
            primary_score=primary_score,
            shadow_score=shadow_score,
            shadow_latency_ms=shadow_latency_ms,
            cost_estimate=cost_estimate,
            shadow_wins=(shadow_score > primary_score),
        )
        db.add(run)
        await db.commit()
        logger.debug(
            "experiment_log primary=%s(%.2f) shadow=%s(%.2f) latency=%.0fms cost=$%.6f",
            primary_provider, primary_score,
            shadow_provider, shadow_score,
            shadow_latency_ms, cost_estimate,
        )


async def get_experiments(limit: int = 100) -> list[dict]:
    """Return the most recent *limit* experiment runs as dictionaries."""
    try:
        from app.models import ExperimentRun
    except ImportError:
        return []

    async with async_session() as db:
        result = await db.execute(
            select(ExperimentRun)
            .order_by(ExperimentRun.created_at.desc())
            .limit(limit)
        )
        runs = result.scalars().all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "primary_provider": r.primary_provider,
                "primary_model": r.primary_model,
                "shadow_provider": r.shadow_provider,
                "shadow_model": r.shadow_model,
                "primary_score": r.primary_score,
                "shadow_score": r.shadow_score,
                "shadow_latency_ms": r.shadow_latency_ms,
                "cost_estimate": r.cost_estimate,
                "shadow_wins": r.shadow_wins,
                "promoted": r.promoted,
                "promotion_approved": r.promotion_approved,
            }
            for r in runs
        ]


async def get_pending_promotion_requests() -> list[str]:
    """Return shadow providers that currently have a pending promotion request."""
    try:
        from app.models import PendingAction, ActionStatus
    except ImportError:
        return []

    async with async_session() as db:
        result = await db.execute(
            select(PendingAction.agent_name)
            .where(
                PendingAction.action_type == "promote_provider",
                PendingAction.status == ActionStatus.PENDING,
            )
            .order_by(PendingAction.created_at.desc())
        )

        providers: list[str] = []
        seen: set[str] = set()
        for (agent_name,) in result.all():
            provider = (agent_name or "").removeprefix("shadow:")
            if not provider or provider in seen:
                continue
            seen.add(provider)
            providers.append(provider)
        return providers


async def check_for_promotion_candidate(
    shadow_provider: str,
    threshold: int = 10,
) -> Optional[dict]:
    """Check if the given shadow provider has won enough consecutive runs to merit promotion.

    If it has, and no promotion action is already pending, insert a PendingAction into
    the ApprovalQueue for user approval.

    Returns the promotion dict if a new candidate was surfaced, else None.
    """
    try:
        from app.models import ExperimentRun, PendingAction, ActionStatus
    except ImportError:
        return None

    async with async_session() as db:
        # Count consecutive recent wins for this shadow provider (not yet promoted)
        result = await db.execute(
            select(ExperimentRun)
            .where(
                ExperimentRun.shadow_provider == shadow_provider,
                ExperimentRun.shadow_wins.is_(True),
                ExperimentRun.promoted.is_(False),
            )
            .order_by(ExperimentRun.created_at.desc())
            .limit(threshold)
        )
        recent_wins = result.scalars().all()

        if len(recent_wins) < threshold:
            return None  # Not enough wins yet

        # Check there isn't already a pending promotion for this provider
        existing = await db.execute(
            select(PendingAction).where(
                PendingAction.action_type == "promote_provider",
                PendingAction.agent_name == f"shadow:{shadow_provider}",
                PendingAction.status == ActionStatus.PENDING,
            )
        )
        if existing.scalar_one_or_none():
            return None  # Already pending

        # Surface a promotion candidate in the ApprovalQueue
        avg_shadow = sum(r.shadow_score for r in recent_wins) / len(recent_wins)
        avg_primary = sum(r.primary_score for r in recent_wins) / len(recent_wins)
        avg_latency = sum(r.shadow_latency_ms for r in recent_wins) / len(recent_wins)
        total_cost_saving = sum(r.cost_estimate for r in recent_wins)

        summary = (
            f"Shadow provider '{shadow_provider}' has outperformed the primary provider "
            f"in {threshold} consecutive tests. "
            f"Avg shadow score: {avg_shadow:.2f} vs primary: {avg_primary:.2f}. "
            f"Avg latency: {avg_latency:.0f}ms. "
            f"Estimated cost saving from last {threshold} runs: ${total_cost_saving:.4f}. "
            f"Approve to promote '{shadow_provider}' as the default provider."
        )

        pending = PendingAction(
            agent_name=f"shadow:{shadow_provider}",
            action_type="promote_provider",
            summary=summary[:200],
            details=summary,
            status=ActionStatus.PENDING,
            risk_level="medium",
        )
        db.add(pending)
        await db.commit()

        logger.info(
            "promotion_candidate provider=%s wins=%d avg_score=%.2f",
            shadow_provider, threshold, avg_shadow,
        )
        return {
            "shadow_provider": shadow_provider,
            "consecutive_wins": threshold,
            "avg_shadow_score": avg_shadow,
            "avg_primary_score": avg_primary,
        }
