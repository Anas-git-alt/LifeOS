import asyncio
from app.services.orchestrator import handle_message
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    print("Testing orchestrator directly...")
    result = await handle_message("sandbox", "What is the price of Bitcoin today?")
    print("Response:", result["response"])

if __name__ == "__main__":
    asyncio.run(main())
