"""Jobs service tests."""

from datetime import datetime, timezone

from freezegun import freeze_time

from app.services.jobs import compute_next_run, normalize_cron_expression, prepare_job_payload


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


def test_prepare_job_payload_preserves_discord_once_run_at_as_utc():
    payload = prepare_job_payload(
        {
            "name": "Discord once job",
            "agent_name": "sandbox",
            "schedule_type": "once",
            "run_at": datetime(2026, 3, 25, 7, 16, 57, 381182),
            "timezone": "Africa/Casablanca",
            "notification_mode": "channel",
            "target_channel": "test",
            "source": "discord_nl",
        }
    )
    assert payload["run_at"] == datetime(2026, 3, 25, 7, 16, 57, 381182)


@freeze_time("2026-03-02 06:15:00")
def test_compute_next_run_is_timezone_aware():
    now = datetime.now(timezone.utc)
    nxt = compute_next_run("30 7 mon-fri", "Africa/Casablanca", now=now)
    assert nxt is not None
    assert nxt.tzinfo is not None
