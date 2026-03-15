"""Web Search Tool — uses DuckDuckGo (free, no API key needed)."""

import asyncio
import httpx
import logging
from typing import List, Dict
from app.config import settings
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


async def _brave_search(query: str, max_results: int) -> List[Dict]:
    """Search using Brave Search API."""
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": settings.brave_api_key
    }
    params = {"q": query, "count": max_results}
    
    logger.info("Connecting to Brave Search API")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            logger.info(f"Brave Search API response status: {response.status_code}")
            
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", "")
            })
        logger.info(f"Parsed {len(results)} results from Brave.")
        return results
    except Exception as e:
        logger.error(f"Brave API error: {e}")
        raise


def _ddg_search_sync(query: str, max_results: int) -> List[Dict]:
    """Blocking DuckDuckGo search. Run in a thread to avoid event-loop stalls."""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")
            }
            for r in results
        ]


async def _ddg_search(query: str, max_results: int) -> List[Dict]:
    """Search using DuckDuckGo without blocking the event loop."""
    return await asyncio.to_thread(_ddg_search_sync, query, max_results)


async def web_search(query: str, max_results: int = 5) -> List[Dict]:
    """Search the web using Brave (if key provided) or DuckDuckGo.

    Brave Search is preferred because DuckDuckGo often rate-limits (202 response).
    """
    try:
        if settings.brave_api_key:
            logger.info("Using Brave Search")
            return await _brave_search(query, max_results)
        else:
            logger.info("Using DuckDuckGo search")
            return await _ddg_search(query, max_results)
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return []
