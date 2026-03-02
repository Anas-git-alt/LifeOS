"""Prayer service unit tests."""

from app.services.prayer_service import _choose_scored_status, _parse_hhmm


def test_parse_hhmm_with_suffix():
    parsed = _parse_hhmm("05:41 (+01)")
    assert parsed.hour == 5
    assert parsed.minute == 41


def test_retroactive_on_time_downgraded_to_late():
    assert _choose_scored_status("on_time", is_retroactive=True) == "late"


def test_non_retroactive_keeps_status():
    assert _choose_scored_status("on_time", is_retroactive=False) == "on_time"
    assert _choose_scored_status("late", is_retroactive=False) == "late"
    assert _choose_scored_status("missed", is_retroactive=False) == "missed"
