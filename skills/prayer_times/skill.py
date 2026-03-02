"""Prayer Times Skill — calculates Islamic prayer times using free API."""

import httpx
from datetime import date


async def get_prayer_times(city: str = "Sofia", country: str = "Bulgaria", method: int = 2) -> dict:
    """Fetch today's prayer times from Aladhan API (free, no key needed).

    Methods: 1=MWL, 2=ISNA, 3=Egypt, 4=Makkah, 5=Karachi
    API docs: https://aladhan.com/prayer-times-api
    """
    today = date.today().strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timingsByCity/{today}"
    params = {
        "city": city,
        "country": country,
        "method": method
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    timings = data["data"]["timings"]
    prayers = {
        "Fajr": timings["Fajr"],
        "Dhuhr": timings["Dhuhr"],
        "Asr": timings["Asr"],
        "Maghrib": timings["Maghrib"],
        "Isha": timings["Isha"],
    }

    return {
        "date": today,
        "city": city,
        "country": country,
        "prayers": prayers,
        "sunrise": timings.get("Sunrise", ""),
        "sunset": timings.get("Sunset", ""),
    }


def format_prayer_schedule(prayer_data: dict) -> str:
    """Format prayer times as a readable message."""
    lines = [
        f"🕌 **Prayer Times — {prayer_data['city']}, {prayer_data['country']}**",
        f"📅 {prayer_data['date']}",
        ""
    ]
    emoji_map = {"Fajr": "🌅", "Dhuhr": "☀️", "Asr": "🌤️", "Maghrib": "🌇", "Isha": "🌙"}
    for name, time in prayer_data["prayers"].items():
        lines.append(f"  {emoji_map.get(name, '🕐')} **{name}**: {time}")

    if prayer_data.get("sunrise"):
        lines.append(f"\n  🌅 Sunrise: {prayer_data['sunrise']}")
    if prayer_data.get("sunset"):
        lines.append(f"  🌇 Sunset: {prayer_data['sunset']}")

    return "\n".join(lines)
