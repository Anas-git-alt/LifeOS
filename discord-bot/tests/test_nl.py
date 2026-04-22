"""NL parser tests for Discord automation commands."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bot.nl import parse_agent_prompt, parse_commitment_prompt, parse_schedule_prompt, parse_schedule_value


def test_parse_schedule_prompt_extracts_cron_and_channel():
    parsed = parse_schedule_prompt(
        "Every weekday at 7:30 remind me to stretch in #fitness-log using health-fitness",
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )
    assert parsed["missing"] == []
    assert parsed["data"]["schedule_type"] == "cron"
    assert parsed["data"]["cron_expression"] == "30 7 mon-fri"
    assert parsed["data"]["target_channel"] == "fitness-log"
    assert parsed["data"]["notification_mode"] == "channel"
    assert parsed["data"]["agent_name"] == "health-fitness"
    assert parsed["data"]["prompt_template"] == "stretch"


def test_parse_schedule_prompt_supports_channel_mentions_and_once_jobs():
    parsed = parse_schedule_prompt(
        "Tomorrow at 9am remind me to review /workspace/docs/spec.md notify in <#123456789012345678> using sandbox",
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )
    assert parsed["missing"] == []
    assert parsed["data"]["schedule_type"] == "once"
    assert parsed["data"]["target_channel_id"] == "123456789012345678"
    assert parsed["data"]["notification_mode"] == "channel"
    assert parsed["data"]["prompt_template"] == "review /workspace/docs/spec.md"


def test_parse_schedule_prompt_normalizes_hidden_channel_characters():
    parsed = parse_schedule_prompt(
        "send me a notification in 2 min to buy medicine in #\u2060test using sandbox",
        now=datetime(2026, 3, 25, 7, 14, tzinfo=timezone.utc),
    )
    assert parsed["missing"] == []
    assert parsed["data"]["schedule_type"] == "once"
    assert parsed["data"]["notification_mode"] == "channel"
    assert parsed["data"]["target_channel"] == "test"


def test_parse_schedule_prompt_defaults_to_silent_without_channel():
    parsed = parse_schedule_prompt(
        "in 10 min remind me to review the notes using sandbox",
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )
    assert parsed["missing"] == []
    assert parsed["data"]["schedule_type"] == "once"
    assert parsed["data"]["notification_mode"] == "silent"
    assert parsed["data"]["target_channel"] is None


def test_parse_schedule_prompt_requests_followups_when_missing_fields():
    parsed = parse_schedule_prompt("remind me to stretch")
    assert "agent_name" in parsed["missing"]
    assert "schedule" in parsed["missing"]
    assert parsed["data"]["notification_mode"] == "silent"


def test_parse_schedule_value_rejects_past_one_time_schedule():
    parsed = parse_schedule_value(
        "today at 7:00",
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )
    assert parsed["data"] == {}
    assert parsed["errors"]


def test_parse_agent_prompt_requires_core_fields():
    parsed = parse_agent_prompt("create an agent")
    assert "name" in parsed["missing"]
    assert "purpose" in parsed["missing"]
    assert "discord_channel" in parsed["missing"]
    assert "cadence" in parsed["missing"]
    assert "approval_policy" in parsed["missing"]


def test_parse_agent_prompt_extracts_mandatory_fields():
    parsed = parse_agent_prompt(
        "Create agent named study-coach to keep me focused in #planning every day at 8:00 approval auto"
    )
    assert parsed["missing"] == []
    assert parsed["data"]["name"] == "study-coach"
    assert parsed["data"]["discord_channel"] == "planning"
    assert parsed["data"]["cadence"] == "0 8 *"
    assert parsed["data"]["config_json"]["approval_policy"] == "auto"


def test_parse_commitment_prompt_extracts_one_time_due_at():
    parsed = parse_commitment_prompt(
        "Send invoice tomorrow at 9am Africa/Casablanca",
        now=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
    )
    assert parsed["errors"] == []
    assert parsed["data"]["timezone"] == "Africa/Casablanca"
    assert parsed["data"]["message"] == "Send invoice"
    assert parsed["data"]["due_at"] == datetime(2026, 3, 26, 8, 0)


def test_parse_commitment_prompt_extracts_before_time_due_at():
    parsed = parse_commitment_prompt(
        "request papers from HR about tax reimbursement today before 5pm",
        now=datetime(2026, 4, 22, 11, 15, tzinfo=timezone.utc),
    )
    expected = (
        datetime(2026, 4, 22, 17, 0, tzinfo=ZoneInfo("Africa/Casablanca"))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    assert parsed["errors"] == []
    assert parsed["data"]["message"] == "request papers from HR about tax reimbursement"
    assert parsed["data"]["due_at"] == expected


def test_parse_commitment_prompt_extracts_today_eod_due_at():
    parsed = parse_commitment_prompt(
        "specific action is to create the canva file and add a few elements, deadline is today eod",
        now=datetime(2026, 4, 22, 10, 44, tzinfo=timezone.utc),
    )
    expected = (
        datetime(2026, 4, 22, 23, 59, tzinfo=ZoneInfo("Africa/Casablanca"))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    assert parsed["errors"] == []
    assert parsed["data"]["message"] == "specific action is to create the canva file and add a few elements"
    assert parsed["data"]["due_at"] == expected


def test_parse_commitment_prompt_extracts_tomorrow_end_of_day_due_at():
    parsed = parse_commitment_prompt(
        "finish the video by tomorrow end of day",
        now=datetime(2026, 4, 22, 10, 44, tzinfo=timezone.utc),
    )
    expected = (
        datetime(2026, 4, 23, 23, 59, tzinfo=ZoneInfo("Africa/Casablanca"))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    assert parsed["errors"] == []
    assert parsed["data"]["message"] == "finish the video"
    assert parsed["data"]["due_at"] == expected


def test_parse_commitment_prompt_rejects_recurring_schedule():
    parsed = parse_commitment_prompt("Stretch every day at 8:00")
    assert parsed["errors"]
