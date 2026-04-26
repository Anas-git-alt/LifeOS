from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database import async_session
from app.models import Agent
from app.services.seed import seed_default_agents


@pytest.mark.asyncio
async def test_seed_refreshes_work_ai_prompt_when_old_prompt_lacks_new_rules():
    async with async_session() as db:
        db.add(
            Agent(
                name="work-ai-influencer",
                description="old",
                provider="openrouter",
                model="openrouter/free",
                system_prompt=(
                    "You are the Work & AI Content agent.\n"
                    "Do not force every on-demand question into social content format."
                ),
                enabled=True,
            )
        )
        await db.commit()

    await seed_default_agents()

    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name == "work-ai-influencer"))
        agent = result.scalar_one()

    assert "If the user just greets you, greet briefly and ask what they need" in (agent.system_prompt or "")
    assert "Never output analysis like 'the user asks'" in (agent.system_prompt or "")
