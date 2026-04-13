import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.tools.web_search import web_search

async def main():
    print("Running web search test...")
    results = await web_search("Bitcoin today", 2)
    print("Results:", results)

if __name__ == "__main__":
    asyncio.run(main())
