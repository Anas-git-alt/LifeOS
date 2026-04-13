import asyncio
from app.database import async_session
from app.models import Agent
from sqlalchemy import select

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
