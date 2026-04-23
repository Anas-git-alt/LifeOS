"""Lightweight Discord REST sender for scheduler nudges."""

import logging
from typing import Dict

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


async def send_channel_message_result(channel_name: str | None, content: str, channel_id: str | None = None) -> dict:
    """Send a text message and return delivery metadata."""
    if not channel_id and not channel_name:
        return {"delivered": False, "channel_id": None, "message_id": None}
    if not settings.discord_bot_token or not settings.discord_guild_id:
        return {"delivered": False, "channel_id": None, "message_id": None}
    resolved_channel_id = str(channel_id or "").strip()
    if not resolved_channel_id:
        await _load_channel_cache()
        resolved_channel_id = _channel_cache.get(channel_name or "", "")
        if not resolved_channel_id:
            logger.warning("Discord channel '%s' not found for scheduler nudge", channel_name)
            return {"delivered": False, "channel_id": None, "message_id": None}

    headers = {
        "Authorization": f"Bot {settings.discord_bot_token}",
        "Content-Type": "application/json",
    }
    payload = {"content": content[:1900]}
    url = f"https://discord.com/api/v10/channels/{resolved_channel_id}/messages"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.is_success:
            body = resp.json()
            return {
                "delivered": True,
                "channel_id": str(body.get("channel_id") or resolved_channel_id),
                "message_id": str(body.get("id") or ""),
            }
        logger.warning("Failed sending Discord message (%s): %s", resp.status_code, resp.text[:200])
        return {"delivered": False, "channel_id": resolved_channel_id, "message_id": None}


async def send_channel_message(channel_name: str | None, content: str, channel_id: str | None = None) -> bool:
    """Send a text message to a Discord channel by id when available, else by name."""
    result = await send_channel_message_result(channel_name, content, channel_id=channel_id)
    return bool(result.get("delivered"))
