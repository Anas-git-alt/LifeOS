"""Helpers for applying agent payloads with workspace defaults."""

from __future__ import annotations

from app.models import Agent, AgentCreate, AgentUpdate
from app.services.workspace import workspace_paths_for_payload


def default_agent_workspace_paths() -> list[str]:
    return workspace_paths_for_payload(None)


def agent_create_kwargs(data: AgentCreate) -> dict:
    payload = data.model_dump()
    payload["workspace_paths_json"] = workspace_paths_for_payload(payload.pop("workspace_paths", None))
    return payload


def build_agent_row(data: AgentCreate) -> Agent:
    return Agent(**agent_create_kwargs(data))


def apply_agent_update(agent: Agent, data: AgentUpdate) -> Agent:
    payload = data.model_dump(exclude_unset=True)
    if "workspace_paths" in payload:
        agent.workspace_paths_json = workspace_paths_for_payload(payload.pop("workspace_paths"))
    elif not agent.workspace_paths_json:
        agent.workspace_paths_json = default_agent_workspace_paths()

    for key, value in payload.items():
        setattr(agent, key, value)

    if not agent.workspace_paths_json:
        agent.workspace_paths_json = default_agent_workspace_paths()
    return agent
