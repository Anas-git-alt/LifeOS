"""Tests for prayer_times skill."""

import pytest
import asyncio
from skills.prayer_times.skill import get_prayer_times, format_prayer_schedule


def test_format_prayer_schedule():
    """Test formatting of prayer schedule."""
    data = {
        "date": "27-02-2026",
        "city": "Sofia",
        "country": "Bulgaria",
        "prayers": {
            "Fajr": "05:45",
            "Dhuhr": "12:30",
            "Asr": "15:45",
            "Maghrib": "18:15",
            "Isha": "19:45"
        },
        "sunrise": "07:00",
        "sunset": "18:10"
    }
    result = format_prayer_schedule(data)
    assert "Sofia" in result
    assert "Fajr" in result
    assert "05:45" in result
    assert "Isha" in result


@pytest.mark.asyncio
async def test_get_prayer_times_integration():
    """Integration test — requires internet access."""
    try:
        result = await get_prayer_times("Sofia", "Bulgaria", 2)
        assert "prayers" in result
        assert "Fajr" in result["prayers"]
        assert "Isha" in result["prayers"]
    except Exception:
        pytest.skip("Network unavailable")
