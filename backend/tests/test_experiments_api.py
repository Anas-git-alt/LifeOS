from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import settings
from app.database import async_session
from app.main import app
from app.models import ActionStatus, ExperimentRun, PendingAction


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


async def _seed_experiment_data() -> None:
    async with async_session() as db:
        db.add(
            ExperimentRun(
                primary_provider="openrouter",
                primary_model="openrouter/auto",
                shadow_provider="nvidia",
                shadow_model="meta/llama-3.1-8b-instruct",
                primary_score=0.7,
                shadow_score=0.9,
                shadow_latency_ms=820,
                cost_estimate=0.00021,
                shadow_wins=True,
                promoted=False,
            )
        )
        db.add(
            PendingAction(
                agent_name="shadow:nvidia",
                action_type="promote_provider",
                summary="Shadow provider nvidia outperformed primary in consecutive tests.",
                details="Approve to promote nvidia as the default provider.",
                status=ActionStatus.PENDING,
                risk_level="medium",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            PendingAction(
                agent_name="shadow:openrouter",
                action_type="promote_provider",
                summary="Resolved promotion request.",
                details="Already handled.",
                status=ActionStatus.APPROVED,
                risk_level="medium",
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


def test_experiments_api_returns_pending_promotion_providers():
    import asyncio

    asyncio.run(_seed_experiment_data())

    with TestClient(app) as client:
        response = client.get("/api/experiments?limit=50", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["pending_promotions"] == ["nvidia"]
    assert payload["experiments"][0]["shadow_provider"] == "nvidia"
