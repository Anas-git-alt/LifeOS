"""Orchestrator policy and chat-flow tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import AuditLog, PendingAction
from app.services.agent_state import AgentStateUnavailableError
from app.services.openviking_client import OpenVikingUnavailableError
from app.services.orchestrator import _extract_and_upsert_intake_entry, _extract_intake_payload, handle_message, run_scheduled_agent
from app.services.turn_planner import TurnPlan
from app.services.risk_engine import (
    classify_risk,
    is_approval_eligible_action_type,
    should_require_approval,
)
from app.services.workspace import WorkspaceExecutionResult


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDbSession:
    def __init__(self, agent):
        self._agent = agent
        self.added: list[object] = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _query):
        return _FakeResult(self._agent)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None


class _FakeSessionFactory:
    def __init__(self, agent):
        self.session = _FakeDbSession(agent)

    def __call__(self):
        return self.session


def _make_agent(*, workspace_enabled: bool = False):
    return SimpleNamespace(
        name="sandbox",
        enabled=True,
        system_prompt="You are the sandbox agent.",
        provider="openrouter",
        model="openrouter/free",
        fallback_provider=None,
        fallback_model=None,
        workspace_enabled=workspace_enabled,
        config_json={"use_web_search": False},
    )


def _make_session(session_id: int, title: str):
    return SimpleNamespace(id=session_id, title=title)


@pytest.fixture(autouse=True)
def _ground_state_packet(monkeypatch):
    monkeypatch.setattr(
        "app.services.orchestrator.build_agent_state_packet",
        AsyncMock(
            return_value={
                "grounded": True,
                "strict": True,
                "generated_at": "2026-04-25T00:00:00+00:00",
                "sources": ["today_agenda"],
                "warnings": [],
                "shared_memory_hits": [],
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.render_agent_state_packet",
        lambda packet: "[LIFEOS STATE PACKET]\n{\"grounded\": true}",
    )


def test_classify_risk_low():
    assert classify_risk("status update please") == "low"


def test_classify_risk_high():
    assert classify_risk("please send email and execute purchase") == "high"


def test_approval_auto_medium_high():
    needs, risk, action_type = should_require_approval(
        user_message="remind me about my deadline tomorrow",
        response_text="I will set reminder",
        approval_policy="auto",
    )
    assert risk in {"medium", "high"}
    assert action_type in {"reminder", "deadline", "message"}
    assert needs is True


def test_approval_never_forced_off():
    needs, risk, _ = should_require_approval(
        user_message="deadline",
        response_text="will do",
        approval_policy="never",
    )
    assert needs is False
    assert risk == "low"


def test_approval_auto_ignores_assistant_keyword_false_positive():
    needs, risk, action_type = should_require_approval(
        user_message="what is the list of md files that are in /docs folder",
        response_text=(
            "I can only write, replace, delete, or restore files. "
            "I cannot list directory contents from here."
        ),
        approval_policy="auto",
    )
    assert needs is False
    assert risk == "low"
    assert action_type == "message"


def test_approval_auto_ignores_schedule_keyword_from_search_results():
    needs, risk, action_type = should_require_approval(
        user_message="what was the subject of session #54",
        response_text="Movie/TV Screening Season #54 - Part of a 2026 screening schedule.",
        approval_policy="auto",
    )
    assert needs is False
    assert risk == "low"
    assert action_type == "message"


def test_only_executable_actions_are_approval_eligible():
    assert is_approval_eligible_action_type("create_job") is True
    assert is_approval_eligible_action_type("create_agent") is True
    assert is_approval_eligible_action_type("workspace_delete") is True
    assert is_approval_eligible_action_type("message") is False
    assert is_approval_eligible_action_type("deadline") is False


def test_extract_intake_payload_strips_machine_block():
    cleaned, payload, saw_machine_block = _extract_intake_payload(
        "Need 2 answers before this is ready.\n\n"
        "[INTAKE_JSON]\n"
        '{"title":"Fix sleep","kind":"goal","domain":"health","status":"clarifying","summary":"Sleep routine needs work","desired_outcome":"7.5h sleep","next_action":"Pick a bedtime","follow_up_questions":["What bedtime is realistic?"],"life_item":{"title":"Fix sleep routine","kind":"goal","domain":"health","priority":"high","start_date":"2026-04-11"}}\n'
        "[/INTAKE_JSON]"
    )

    assert cleaned == "Need 2 answers before this is ready."
    assert payload["title"] == "Fix sleep"
    assert payload["follow_up_questions"] == ["What bedtime is realistic?"]
    assert saw_machine_block is True


def test_extract_intake_payload_strips_partial_machine_block():
    cleaned, payload, saw_machine_block = _extract_intake_payload(
        "Need 2 answers before this is ready.\n\n"
        "[INTAKE_JSON]\n"
        '{"title":"Fix sleep","summary"'
    )

    assert cleaned == "Need 2 answers before this is ready."
    assert payload is None
    assert saw_machine_block is True


def test_extract_intake_payload_parses_unclosed_complete_block():
    cleaned, payload, saw_machine_block = _extract_intake_payload(
        "Ready to track.\n\n"
        "[INTAKE_JSON]\n"
        '{"title":"Create one pager","kind":"commitment","domain":"work","status":"ready","summary":"Create one pager","desired_outcome":"One pager done","next_action":"Open draft","follow_up_questions":[],"life_item":{"title":"Create one pager","kind":"task","domain":"work","priority":"medium"}}'
    )

    assert cleaned == "Ready to track."
    assert payload["title"] == "Create one pager"
    assert payload["life_item"]["title"] == "Create one pager"
    assert saw_machine_block is True


@pytest.mark.asyncio
async def test_commitment_capture_agent_creates_intake_entry(monkeypatch):
    calls = {}

    async def _fake_upsert(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(id=42)

    monkeypatch.setattr("app.services.orchestrator.upsert_intake_entry_from_agent", _fake_upsert)

    result = await _extract_and_upsert_intake_entry(
        agent_name="commitment-capture",
        response_text=(
            "Ready to track.\n\n"
            "[INTAKE_JSON]\n"
            '{"title":"Create one pager","kind":"commitment","domain":"work","status":"ready","summary":"Create one pager","desired_outcome":"One pager done","next_action":"Open draft","follow_up_questions":[],"life_item":{"title":"Create one pager","kind":"task","domain":"work","priority":"medium"}}\n'
            "[/INTAKE_JSON]"
        ),
        user_message="create a one pager tomorrow at 10pm",
        session_id=9,
    )

    assert result == {"cleaned_text": "Ready to track.", "entry_id": 42}
    assert calls["agent_name"] == "commitment-capture"
    assert calls["payload"]["status"] == "ready"


@pytest.mark.asyncio
async def test_handle_message_does_not_create_pending_for_informational_chat(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    factory = _FakeSessionFactory(agent)
    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.orchestrator.chat_completion",
        AsyncMock(
            return_value=(
                "I can explain your options and mention delete or schedule keywords, "
                "but no actual task will be executed."
            )
        ),
    )
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="what is the list of md files that are in /docs folder",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["pending_action_id"] is None
    assert any(isinstance(row, AuditLog) for row in factory.session.added)
    assert not any(isinstance(row, PendingAction) for row in factory.session.added)
    assert result["grounding"]["grounded"] is True


@pytest.mark.asyncio
async def test_handle_message_answers_memory_recall_without_llm(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    agent.name = "work-ai-influencer"
    factory = _FakeSessionFactory(agent)
    raw_text = (
        "remind me to send a request to HR for tax return papers:\n"
        "Attestation de salaire annuel (36 mois)\n"
        "Attestation de salaire mensuel\n"
        "Attestation de travail\n"
        "Copie du contrat de travail\n"
        "Attestation de declaration de salaire a la CNSS\n"
        "Follow-up answer: Tomorrow before 2pm yes workday"
    )
    hit = SimpleNamespace(
        raw_text=raw_text,
        snippet=raw_text,
        title="Send request to HR",
    )
    chat_completion = AsyncMock(return_value="should not be used")

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.search_memory_events", AsyncMock(return_value=[hit]))
    monkeypatch.setattr("app.services.orchestrator.chat_completion", chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="work-ai-influencer",
        user_message="what papers did I say I need from HR?",
        approval_policy="auto",
        session_enabled=False,
    )

    assert chat_completion.await_count == 0
    assert "Mode B" not in result["response"]
    assert "Attestation de salaire annuel" in result["response"]
    assert "Copie du contrat de travail" in result["response"]
    assert "Tomorrow before 2pm yes workday" in result["response"]


@pytest.mark.asyncio
async def test_handle_message_fails_closed_when_state_packet_unavailable(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    factory = _FakeSessionFactory(agent)
    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr(
        "app.services.orchestrator.build_agent_state_packet",
        AsyncMock(side_effect=AgentStateUnavailableError("today agenda failed")),
    )

    result = await handle_message(
        agent_name="sandbox",
        user_message="what should I do today?",
        approval_policy="never",
        session_enabled=False,
    )

    assert result["error_code"] == "state_packet_unavailable"
    assert result["risk_level"] == "high"
    assert result["grounding"]["grounded"] is False


@pytest.mark.asyncio
async def test_handle_message_saves_cleaned_intake_response(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    agent.name = "intake-inbox"
    factory = _FakeSessionFactory(agent)
    save_message = AsyncMock()

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.chat_completion", AsyncMock(return_value="Visible reply"))
    monkeypatch.setattr("app.services.orchestrator.save_message", save_message)
    monkeypatch.setattr(
        "app.services.orchestrator._extract_and_upsert_intake_entry",
        AsyncMock(return_value={"cleaned_text": "Visible reply", "entry_id": 17}),
    )
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="intake-inbox",
        user_message="I need to fix sleep and training",
        approval_policy="never",
        session_enabled=False,
    )

    assert result["pending_action_id"] is None
    assert save_message.await_args_list[1].args[2] == "Visible reply"


@pytest.mark.asyncio
async def test_run_scheduled_agent_channel_delivery_without_channel_id_override(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    agent.discord_channel = "test"
    factory = _FakeSessionFactory(agent)

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr(
        "app.services.orchestrator.handle_message",
        AsyncMock(return_value={"response": "Check in now."}),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.send_channel_message_result",
        AsyncMock(return_value={"delivered": True, "channel_id": "999", "message_id": "555"}),
    )

    result = await run_scheduled_agent(
        agent_name="sandbox",
        prompt_override="Ask me how day going",
        target_channel_override="test",
        notification_mode_override="channel",
    )

    assert result["status"] == "delivered"
    assert result["notification_channel"] == "test"
    assert result["notification_channel_id"] == "999"
    assert result["notification_message_id"] == "555"


@pytest.mark.asyncio
async def test_handle_message_preserves_workspace_delete_pending(monkeypatch):
    agent = _make_agent(workspace_enabled=True)
    factory = _FakeSessionFactory(agent)
    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.get_openviking_context", AsyncMock(return_value=""))
    monkeypatch.setattr("app.services.orchestrator.get_agent_workspace_paths", lambda _agent: ["/workspace"])
    monkeypatch.setattr(
        "app.services.orchestrator.chat_completion",
        AsyncMock(return_value="Queued a delete request."),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.parse_workspace_actions",
        lambda response_text: (response_text, SimpleNamespace(actions=[{"type": "delete_file"}])),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.apply_workspace_actions",
        AsyncMock(
            return_value=WorkspaceExecutionResult(
                notes=["Queued delete approval as action #77."],
                pending_action_id=77,
            )
        ),
    )
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="delete the docs folder",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["pending_action_id"] == 77
    assert any(isinstance(row, AuditLog) for row in factory.session.added)


@pytest.mark.asyncio
async def test_handle_message_continues_without_memory_context(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    factory = _FakeSessionFactory(agent)
    save_message = AsyncMock()

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr(
        "app.services.orchestrator.get_context",
        AsyncMock(side_effect=OpenVikingUnavailableError("search unavailable")),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.chat_completion",
        AsyncMock(return_value="Recovered answer"),
    )
    monkeypatch.setattr("app.services.orchestrator.save_message", save_message)
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="Reply with exactly: DISCORD_OK",
        approval_policy="never",
        session_enabled=False,
    )

    assert result["response"] == "Recovered answer"
    assert result["pending_action_id"] is None
    assert any("without prior session context" in warning for warning in result["warnings"])
    save_message.assert_awaited()


@pytest.mark.asyncio
async def test_handle_message_returns_reply_when_memory_persistence_fails(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    factory = _FakeSessionFactory(agent)

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.orchestrator.chat_completion",
        AsyncMock(return_value="Recovered answer"),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.save_message",
        AsyncMock(
            side_effect=[
                OpenVikingUnavailableError("user save failed"),
                OpenVikingUnavailableError("assistant save failed"),
            ]
        ),
    )
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="Reply with exactly: DISCORD_OK",
        approval_policy="never",
        session_enabled=False,
    )

    assert result["response"] == "Recovered answer"
    assert result["pending_action_id"] is None
    assert any("could not be saved to OpenViking session memory" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_handle_message_uses_web_search_and_transient_note_without_saving_note(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    agent.config_json = {"use_web_search": True}
    factory = _FakeSessionFactory(agent)
    captured: dict[str, object] = {}

    async def fake_chat_completion(messages, provider, model, fallback_provider, fallback_model, **_kwargs):
        captured["messages"] = messages
        return "Weather answer from search."

    get_search_context = AsyncMock(return_value="[WEB SEARCH RESULTS]\nCasablanca weather result")
    save_message = AsyncMock()

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator._get_search_context", get_search_context)
    monkeypatch.setattr(
        "app.services.orchestrator.plan_turn_for_tools",
        AsyncMock(return_value=TurnPlan(needs_web_search=True, web_search_query="Casablanca weather today", confidence=0.9)),
    )
    monkeypatch.setattr("app.services.orchestrator.chat_completion", fake_chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", save_message)
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="how is the wether today?",
        approval_policy="auto",
        session_enabled=False,
        transient_system_note="Daily log already executed. Do not ask to confirm it again.",
    )

    assert result["response"] == "Weather answer from search."
    get_search_context.assert_awaited_once_with("Casablanca weather today")
    system_text = captured["messages"][0]["content"]
    assert "Web search is available" in system_text
    assert "Daily log already executed" in system_text
    assert "[WEB SEARCH RESULTS]" in captured["messages"][-1]["content"]
    assert save_message.await_args_list[0].args[2] == "how is the wether today?"
    assert "Daily log already executed" not in save_message.await_args_list[0].args[2]


@pytest.mark.asyncio
async def test_handle_message_uses_turn_planner_for_short_location_followup(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    agent.config_json = {"use_web_search": True}
    factory = _FakeSessionFactory(agent)
    captured: dict[str, object] = {}

    async def fake_chat_completion(messages, provider, model, fallback_provider, fallback_model, **_kwargs):
        captured["messages"] = messages
        return "Weather in Casablanca from search."

    planner = AsyncMock(
        return_value=TurnPlan(needs_web_search=True, web_search_query="current weather Casablanca Morocco", confidence=0.95)
    )
    get_search_context = AsyncMock(return_value="[WEB SEARCH RESULTS]\nCasablanca weather")

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr(
        "app.services.orchestrator.get_context",
        AsyncMock(return_value=[{"role": "user", "content": "how is the wether today?"}]),
    )
    monkeypatch.setattr("app.services.orchestrator.plan_turn_for_tools", planner)
    monkeypatch.setattr("app.services.orchestrator._get_search_context", get_search_context)
    monkeypatch.setattr("app.services.orchestrator.chat_completion", fake_chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="casablanca",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["response"] == "Weather in Casablanca from search."
    planner.assert_awaited_once()
    assert planner.await_args.kwargs["state_packet"]["grounded"] is True
    get_search_context.assert_awaited_once_with("current weather Casablanca Morocco")
    assert "Web search query used: current weather Casablanca Morocco" in captured["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_handle_message_does_not_search_web_for_lifeos_today_plan(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    agent.config_json = {"use_web_search": True}
    factory = _FakeSessionFactory(agent)
    planner = AsyncMock(return_value=TurnPlan(needs_web_search=True, web_search_query="what should I do today", confidence=0.9))
    get_search_context = AsyncMock(return_value="[WEB SEARCH RESULTS]")

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.plan_turn_for_tools", planner)
    monkeypatch.setattr("app.services.orchestrator._get_search_context", get_search_context)
    monkeypatch.setattr("app.services.orchestrator.chat_completion", AsyncMock(return_value="LifeOS-only plan."))
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="what should i do today?",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["response"] == "LifeOS-only plan."
    planner.assert_not_awaited()
    get_search_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_adds_profile_location_instruction(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    agent.config_json = {"use_web_search": True}
    factory = _FakeSessionFactory(agent)
    captured: dict[str, object] = {}

    async def fake_chat_completion(messages, provider, model, fallback_provider, fallback_model, **_kwargs):
        captured["messages"] = messages
        return "Local answer."

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.orchestrator.build_agent_state_packet",
        AsyncMock(
            return_value={
                "grounded": True,
                "strict": True,
                "generated_at": "2026-04-26T00:00:00+00:00",
                "sources": ["today_agenda", "user_profile"],
                "warnings": [],
                "profile": {"city": "Casablanca", "country": "Morocco", "timezone": "Africa/Casablanca"},
            }
        ),
    )
    monkeypatch.setattr("app.services.orchestrator.propose_daily_log_payload", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.services.orchestrator.plan_turn_for_tools",
        AsyncMock(return_value=TurnPlan(needs_web_search=False, web_search_query=None, confidence=0.8)),
    )
    monkeypatch.setattr("app.services.orchestrator.chat_completion", fake_chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    await handle_message(
        agent_name="sandbox",
        user_message="what cheap meal should i cook with high protein?",
        approval_policy="auto",
        session_enabled=False,
    )

    system_text = captured["messages"][0]["content"]
    assert "Default user location is Casablanca, Morocco" in system_text
    assert "Prefer local units/currency" in system_text


@pytest.mark.asyncio
async def test_handle_message_uses_session_context_before_daily_log_classifier(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    factory = _FakeSessionFactory(agent)
    active_session = _make_session(6, "Cheap meal")
    session_context = [
        {"role": "assistant", "content": "Here is a cheap high-protein egg meal with ingredients."},
    ]
    proposer = AsyncMock(return_value=None)

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.ensure_session", AsyncMock(return_value=active_session))
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=session_context))
    monkeypatch.setattr("app.services.orchestrator.propose_daily_log_payload", proposer)
    monkeypatch.setattr("app.services.orchestrator.chat_completion", AsyncMock(return_value="Egg meal details."))
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator.refresh_session_metadata", AsyncMock(return_value=active_session))
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.settings.memory_summarisation_enabled", False)

    result = await handle_message(
        agent_name="sandbox",
        user_message="more détails for the egg meal, with per ingrédient price",
        approval_policy="auto",
        session_enabled=True,
        session_id=6,
    )

    assert result["response"] == "Egg meal details."
    assert result["pending_action_id"] is None
    proposer.assert_awaited_once()
    assert proposer.await_args.kwargs["context"] == session_context


@pytest.mark.asyncio
async def test_handle_message_filters_stale_daily_log_proposal_after_execution(monkeypatch):
    agent = _make_agent(workspace_enabled=False)
    factory = _FakeSessionFactory(agent)
    captured: dict[str, object] = {}

    async def fake_chat_completion(messages, provider, model, fallback_provider, fallback_model, **_kwargs):
        captured["messages"] = messages
        return "Continue answer after log."

    stale_context = [
        {"role": "user", "content": "what should i do today? i drank water"},
        {
            "role": "assistant",
            "content": "I can log this in Today: hydration x1.\n\nReact with ✅ to apply it.",
        },
    ]

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=stale_context))
    propose_daily_log_payload = AsyncMock(return_value={"logs": [{"kind": "hydration", "count": 1}], "source_text": "x"})
    monkeypatch.setattr("app.services.orchestrator.propose_daily_log_payload", propose_daily_log_payload)
    monkeypatch.setattr("app.services.orchestrator.chat_completion", fake_chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="what should I do today? i drank water",
        approval_policy="never",
        session_enabled=False,
        transient_system_note="Daily log approval was executed. Do not ask to confirm it again.",
    )

    assert result["response"] == "Continue answer after log."
    context_text = "\n".join(str(message.get("content") or "") for message in captured["messages"])
    propose_daily_log_payload.assert_not_awaited()
    assert "I can log this in Today" not in context_text
    assert "React with ✅" not in context_text
    assert "approval already executed" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_handle_message_uses_referenced_session_without_switching_active_session(monkeypatch):
    agent = SimpleNamespace(**_make_agent(workspace_enabled=False).__dict__)
    agent.config_json = {"use_web_search": True}
    factory = _FakeSessionFactory(agent)
    active_session = _make_session(62, "Current session")
    captured: dict[str, object] = {}

    async def fake_chat_completion(messages, provider, model, fallback_provider, fallback_model, **_kwargs):
        captured["messages"] = messages
        return "Session #54 was about summarizing the repo."

    save_message = AsyncMock()
    get_search_context = AsyncMock(return_value="[WEB SEARCH RESULTS]")

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.ensure_session", AsyncMock(return_value=active_session))
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.orchestrator.build_session_reference_context",
        AsyncMock(return_value="[REFERENCED SESSION CONTEXT]\nReferenced session id: 54\nReferenced session title: Summarize this repo"),
    )
    monkeypatch.setattr("app.services.orchestrator.chat_completion", fake_chat_completion)
    monkeypatch.setattr("app.services.orchestrator._get_search_context", get_search_context)
    monkeypatch.setattr("app.services.orchestrator.save_message", save_message)
    monkeypatch.setattr("app.services.orchestrator.refresh_session_metadata", AsyncMock(return_value=active_session))
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.settings.memory_summarisation_enabled", False)

    result = await handle_message(
        agent_name="sandbox",
        user_message="what was the subject of session #54?",
        approval_policy="auto",
        session_id=62,
        session_enabled=True,
    )

    assert result["session_id"] == 62
    assert result["session_title"] == "Current session"
    assert get_search_context.await_count == 0
    assert any(
        message["role"] == "system" and "Referenced session id: 54" in message["content"]
        for message in captured["messages"]
    )
    assert save_message.await_args_list[0].kwargs["session_id"] == 62
    assert save_message.await_args_list[1].kwargs["session_id"] == 62


@pytest.mark.asyncio
async def test_handle_message_returns_direct_response_when_referenced_session_is_missing(monkeypatch):
    agent = SimpleNamespace(**_make_agent(workspace_enabled=False).__dict__)
    agent.config_json = {"use_web_search": True}
    factory = _FakeSessionFactory(agent)
    active_session = _make_session(62, "Current session")
    save_message = AsyncMock()
    chat_completion = AsyncMock(return_value="should not be used")

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.ensure_session", AsyncMock(return_value=active_session))
    monkeypatch.setattr(
        "app.services.orchestrator.build_session_reference_context",
        AsyncMock(side_effect=ValueError("missing")),
    )
    monkeypatch.setattr("app.services.orchestrator.chat_completion", chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", save_message)
    monkeypatch.setattr("app.services.orchestrator.refresh_session_metadata", AsyncMock(return_value=active_session))
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.settings.memory_summarisation_enabled", False)

    result = await handle_message(
        agent_name="sandbox",
        user_message="what was the subject of session #9999?",
        approval_policy="auto",
        session_id=62,
        session_enabled=True,
    )

    assert "couldn't find `sandbox` session #9999" in result["response"].lower()
    assert result["session_id"] == 62
    assert chat_completion.await_count == 0
    assert save_message.await_count == 2


@pytest.mark.asyncio
async def test_handle_message_skips_web_search_for_follow_up_memory_prompt(monkeypatch):
    agent = SimpleNamespace(**_make_agent(workspace_enabled=False).__dict__)
    agent.config_json = {"use_web_search": True}
    factory = _FakeSessionFactory(agent)
    get_search_context = AsyncMock(return_value="[WEB SEARCH RESULTS]")

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr(
        "app.services.orchestrator.get_context",
        AsyncMock(return_value=[{"role": "user", "content": "remember this exact phrase: blue cactus"}]),
    )
    monkeypatch.setattr("app.services.orchestrator._get_search_context", get_search_context)
    monkeypatch.setattr("app.services.orchestrator.chat_completion", AsyncMock(return_value="blue cactus"))
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="what phrase did i ask you to remember?",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["response"] == "blue cactus"
    assert get_search_context.await_count == 0


@pytest.mark.asyncio
async def test_handle_message_continues_when_workspace_context_is_unavailable(monkeypatch):
    agent = _make_agent(workspace_enabled=True)
    factory = _FakeSessionFactory(agent)

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.get_agent_workspace_paths", lambda _agent: ["/workspace"])
    monkeypatch.setattr(
        "app.services.orchestrator.get_openviking_context",
        AsyncMock(side_effect=OpenVikingUnavailableError("Connection error")),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.chat_completion",
        AsyncMock(return_value="I can help once you share the filenames."),
    )
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="what is the list of md files that are in /docs folder",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result.get("error_code") is None
    assert result["pending_action_id"] is None
    assert result["response"] == "I can help once you share the filenames."


@pytest.mark.asyncio
async def test_handle_message_rewrites_false_workspace_success_claims(monkeypatch):
    agent = _make_agent(workspace_enabled=True)
    factory = _FakeSessionFactory(agent)

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.get_agent_workspace_paths", lambda _agent: ["/workspace"])
    monkeypatch.setattr("app.services.orchestrator.get_openviking_context", AsyncMock(return_value=""))
    monkeypatch.setattr(
        "app.services.orchestrator.chat_completion",
        AsyncMock(
            return_value=(
                "File deletion request submitted! The file /workspace/tmp/discord-sandbox-delete-test.md "
                "has been queued for deletion."
            )
        ),
    )
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="can you take care of /workspace/tmp/discord-sandbox-delete-test.md for me?",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["pending_action_id"] is None
    assert "did not include a valid [WORKSPACE_ACTIONS] block" in result["response"]
    assert "queued for deletion" not in result["response"].lower()


@pytest.mark.asyncio
async def test_handle_message_answers_directory_listing_without_llm(monkeypatch):
    agent = _make_agent(workspace_enabled=True)
    factory = _FakeSessionFactory(agent)
    chat_completion = AsyncMock(return_value="should not be used")

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.get_agent_workspace_paths", lambda _agent: ["/workspace"])
    monkeypatch.setattr(
        "app.services.orchestrator.describe_workspace_listing_request",
        lambda _message, _paths: "Here are the files in `docs`:\n- `docs/README.md`",
    )
    monkeypatch.setattr("app.services.orchestrator.chat_completion", chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="give list files inside docs folder that's this workspace",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["response"] == "Here are the files in `docs`:\n- `docs/README.md`"
    assert result["pending_action_id"] is None
    assert chat_completion.await_count == 0


@pytest.mark.asyncio
async def test_handle_message_uses_read_only_workspace_instructions_for_repo_questions(monkeypatch):
    agent = _make_agent(workspace_enabled=True)
    factory = _FakeSessionFactory(agent)
    captured: dict[str, object] = {}

    async def fake_chat_completion(messages, provider, model, fallback_provider, fallback_model, **_kwargs):
        captured["messages"] = messages
        return "Here is the repo summary."

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.get_agent_workspace_paths", lambda _agent: ["/workspace"])
    monkeypatch.setattr("app.services.orchestrator.describe_workspace_listing_request", lambda _message, _paths: None)
    monkeypatch.setattr("app.services.orchestrator.get_openviking_context", AsyncMock(return_value=""))
    monkeypatch.setattr("app.services.orchestrator.chat_completion", fake_chat_completion)
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="summarize the docs folder structure",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["response"] == "Here is the repo summary."
    assert "Do not include [WORKSPACE_ACTIONS]" in captured["messages"][0]["content"]
    assert "You may modify files only" not in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_handle_message_inferrs_direct_delete_into_real_workspace_approval(monkeypatch):
    agent = _make_agent(workspace_enabled=True)
    factory = _FakeSessionFactory(agent)

    monkeypatch.setattr("app.services.orchestrator.async_session", factory)
    monkeypatch.setattr("app.services.orchestrator.get_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.orchestrator.get_agent_workspace_paths", lambda _agent: ["/workspace"])
    monkeypatch.setattr("app.services.orchestrator.get_openviking_context", AsyncMock(return_value=""))
    monkeypatch.setattr(
        "app.services.orchestrator.chat_completion",
        AsyncMock(return_value="I can help with that."),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.apply_workspace_actions",
        AsyncMock(
            return_value=WorkspaceExecutionResult(
                notes=["Queued delete approval as action #88."],
                pending_action_id=88,
            )
        ),
    )
    monkeypatch.setattr("app.services.orchestrator.save_message", AsyncMock())
    monkeypatch.setattr("app.services.orchestrator._extract_and_create_goals", AsyncMock(return_value=[]))

    result = await handle_message(
        agent_name="sandbox",
        user_message="delete /workspace/tmp/discord-sandbox-delete-test.md",
        approval_policy="auto",
        session_enabled=False,
    )

    assert result["pending_action_id"] == 88
    assert "queue the requested delete for approval" in result["response"].lower()
