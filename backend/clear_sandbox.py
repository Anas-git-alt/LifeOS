import asyncio
from app.services.memory import clear_memory

async def main():
    print("Clearing memory for sandbox agent...")
    await clear_memory("sandbox")
    print("Memory cleared.")

if __name__ == "__main__":
    asyncio.run(main())
