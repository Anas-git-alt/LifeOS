"""Natural-language parsing helpers for Discord automation commands."""

from __future__ import annotations

import re

DAY_MAP = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}


def _parse_time(text: str) -> tuple[int, int] | None:
    match = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridian = (match.group(3) or "").lower().strip()
    if meridian == "pm" and hour < 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _parse_dow(text: str) -> str | None:
    lowered = text.lower()
    if "every weekday" in lowered or "weekdays" in lowered:
        return "mon-fri"
    if "every day" in lowered or "daily" in lowered:
        return "*"
    if "weekend" in lowered:
        return "sat,sun"
    selected = [abbr for name, abbr in DAY_MAP.items() if f"every {name}" in lowered]
    if selected:
        return ",".join(selected)
    return None


def parse_schedule_prompt(text: str) -> dict:
    lowered = text.lower().strip()
    data: dict = {}
    missing: list[str] = []

    channel_match = re.search(r"#([a-z0-9\-_]+)", lowered)
    if channel_match:
        data["target_channel"] = channel_match.group(1)
    else:
        missing.append("target_channel")

    agent_match = re.search(r"(?:agent|using)\s+([a-z0-9\-_]+)", lowered)
    if agent_match:
        data["agent_name"] = agent_match.group(1)
    else:
        missing.append("agent_name")

    timezone_match = re.search(r"\b([A-Za-z]+/[A-Za-z_]+)\b", text)
    if timezone_match:
        data["timezone"] = timezone_match.group(1)
    else:
        data["timezone"] = "Africa/Casablanca"

    parsed_time = _parse_time(text)
    parsed_dow = _parse_dow(text)
    if parsed_time and parsed_dow:
        hour, minute = parsed_time
        data["cron_expression"] = f"{minute} {hour} {parsed_dow}"
    else:
        missing.append("cron_expression")

    reminder_match = re.search(r"remind me to (.+?)(?:\sin\s#|$)", text, re.IGNORECASE)
    prompt_template = reminder_match.group(1).strip() if reminder_match else text.strip()
    data["prompt_template"] = prompt_template
    data["name"] = f"NL: {prompt_template[:80]}"
    data["description"] = f"Natural-language reminder job: {prompt_template}"
    data["job_type"] = "agent_nudge"
    data["source"] = "discord_nl"
    data["created_by"] = "discord"
    data["approval_required"] = True

    return {"data": data, "missing": missing}


def parse_agent_prompt(text: str) -> dict:
    lowered = text.lower().strip()
    data: dict = {}
    missing: list[str] = []

    name_match = re.search(r"(?:named|name)\s+([a-z0-9\-_]+)", lowered)
    if name_match:
        data["name"] = name_match.group(1)
    else:
        missing.append("name")

    purpose_match = re.search(r"(?:for|to)\s+(.+?)(?:\sin\s#|$)", text, re.IGNORECASE)
    if purpose_match:
        purpose = purpose_match.group(1).strip()
        data["description"] = purpose
        data["system_prompt"] = f"You are {data.get('name', 'a LifeOS agent')}. Purpose: {purpose}"
    else:
        missing.append("purpose")

    channel_match = re.search(r"#([a-z0-9\-_]+)", lowered)
    if channel_match:
        data["discord_channel"] = channel_match.group(1)
    else:
        missing.append("discord_channel")

    schedule = parse_schedule_prompt(text)
    if "cron_expression" not in schedule["missing"]:
        data["cadence"] = schedule["data"]["cron_expression"]
    else:
        missing.append("cadence")

    if "approval always" in lowered:
        data["config_json"] = {"approval_policy": "always"}
    elif "approval never" in lowered:
        data["config_json"] = {"approval_policy": "never"}
    elif "approval auto" in lowered:
        data["config_json"] = {"approval_policy": "auto"}
    else:
        missing.append("approval_policy")

    data.setdefault("provider", "openrouter")
    data.setdefault("model", "openrouter/auto")
    data.setdefault("enabled", True)

    return {"data": data, "missing": missing}
