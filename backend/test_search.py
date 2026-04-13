import asyncio
from app.services.tools.web_search import web_search

async def main():
    print("Running web search test...")
    results = await web_search("Bitcoin today", 2)
    print("Results:", results)

if __name__ == "__main__":
    asyncio.run(main())
