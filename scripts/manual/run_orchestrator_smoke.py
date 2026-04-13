import asyncio
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.orchestrator import handle_message

logging.basicConfig(level=logging.INFO)

async def main():
    print("Testing orchestrator directly...")
    result = await handle_message("sandbox", "What is the price of Bitcoin today?")
    print("Response:", result["response"])

if __name__ == "__main__":
    asyncio.run(main())
