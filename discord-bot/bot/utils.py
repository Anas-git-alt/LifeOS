"""Utility functions for Discord bot API access."""

import os

import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
API_TOKEN = os.getenv("LIFEOS_API_TOKEN") or os.getenv("API_SECRET_KEY", "")


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if API_TOKEN:
        headers["X-LifeOS-Token"] = API_TOKEN
    return headers


async def api_get(path: str):
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{BACKEND_URL}/api{path}", headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def api_post(path: str, data: dict):
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{BACKEND_URL}/api{path}", json=data, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def api_put(path: str, data: dict):
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.put(f"{BACKEND_URL}/api{path}", json=data, headers=_headers())
        resp.raise_for_status()
        return resp.json()
