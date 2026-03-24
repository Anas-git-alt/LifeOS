"""Lightweight Discord REST sender for scheduler nudges."""

import logging
from typing import Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_channel_cache: Dict[str, str] = {}


async def _load_channel_cache() -> None:
    if _channel_cache:
        return
    if not settings.discord_bot_token or not settings.discord_guild_id:
        return

    headers = {"Authorization": f"Bot {settings.discord_bot_token}"}
    url = f"https://discord.com/api/v10/guilds/{settings.discord_guild_id}/channels"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        channels = resp.json()
    for channel in channels:
        if channel.get("type") == 0 and channel.get("name"):  # text channels only
            _channel_cache[channel["name"]] = channel["id"]


async def send_channel_message(channel_name: str, content: str) -> bool:
    """Send a text message to a Discord channel by name."""
    if not channel_name:
        return False
    if not settings.discord_bot_token or not settings.discord_guild_id:
        return False
    await _load_channel_cache()
    channel_id = _channel_cache.get(channel_name)
    if not channel_id:
        logger.warning("Discord channel '%s' not found for scheduler nudge", channel_name)
        return False

    headers = {
        "Authorization": f"Bot {settings.discord_bot_token}",
        "Content-Type": "application/json",
    }
    payload = {"content": content[:1900]}
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.is_success:
            return True
        logger.warning("Failed sending Discord message (%s): %s", resp.status_code, resp.text[:200])
        return False
