import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import async_session
from sqlalchemy import select
from app.models import Agent

async def main():
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.name=='sandbox'))
        agent = result.scalar_one_or_none()
        if agent:
            print("Agent found:", agent.name)
            print("Config JSON:", agent.config_json)
        else:
            print("Agent not found!")

if __name__ == "__main__":
    asyncio.run(main())
