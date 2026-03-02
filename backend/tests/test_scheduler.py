"""Scheduler helper tests."""

from app.services.scheduler import _parse_cadence


def test_parse_cadence_daily():
    minute, hour, dow = _parse_cadence("0 8 *")
    assert minute == "0"
    assert hour == "8"
    assert dow == "*"


def test_parse_cadence_with_list_hours():
    minute, hour, dow = _parse_cadence("0 4,12,15,18,20 *")
    assert minute == "0"
    assert hour == "4,12,15,18,20"
    assert dow == "*"
