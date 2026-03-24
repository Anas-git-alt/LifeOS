"""Jobs service tests."""

from datetime import datetime, timezone

from freezegun import freeze_time

from app.services.jobs import compute_next_run, normalize_cron_expression


def test_normalize_cron_expression_legacy_three_field():
    assert normalize_cron_expression("30 7 mon-fri") == "30 7 * * mon-fri"


def test_normalize_cron_expression_five_field():
    assert normalize_cron_expression("30 7 * * mon-fri") == "30 7 * * mon-fri"


def test_normalize_cron_expression_invalid():
    try:
        normalize_cron_expression("7")
    except ValueError as exc:
        assert "Cron must have either 3 fields" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid cron")


@freeze_time("2026-03-02 06:15:00")
def test_compute_next_run_is_timezone_aware():
    now = datetime.now(timezone.utc)
    nxt = compute_next_run("30 7 mon-fri", "Africa/Casablanca", now=now)
    assert nxt is not None
    assert nxt.tzinfo is not None
