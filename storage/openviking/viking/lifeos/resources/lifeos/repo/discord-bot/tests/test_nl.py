"""NL parser tests for Discord automation commands."""

from bot.nl import parse_agent_prompt, parse_schedule_prompt


def test_parse_schedule_prompt_extracts_cron_and_channel():
    parsed = parse_schedule_prompt("Every weekday at 7:30 remind me to stretch in #fitness-log using health-fitness")
    assert parsed["missing"] == []
    assert parsed["data"]["cron_expression"] == "30 7 mon-fri"
    assert parsed["data"]["target_channel"] == "fitness-log"
    assert parsed["data"]["agent_name"] == "health-fitness"


def test_parse_schedule_prompt_requests_followups_when_missing_fields():
    parsed = parse_schedule_prompt("remind me to stretch")
    assert "target_channel" in parsed["missing"]
    assert "agent_name" in parsed["missing"]
    assert "cron_expression" in parsed["missing"]


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
