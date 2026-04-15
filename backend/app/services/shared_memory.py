"""Shared-memory routing, search, and promotion over an Obsidian vault."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import Agent, SharedMemoryProposal, SharedMemorySearchHit
from app.services.openviking_client import openviking_client
from app.services.vault import (
    DEFAULT_SHARED_DOMAINS,
    OBSIDIAN_RESOURCE_URI,
    classify_note_path,
    ensure_obsidian_vault_layout,
    note_checksum,
    obsidian_index_root,
    obsidian_private_root,
    obsidian_shared_root,
    obsidian_vault_enabled,
    obsidian_vault_root,
    render_managed_note,
    slugify_note,
    sync_obsidian_vault_resources,
    vault_note_uri,
)
from app.services.workspace import WorkspaceAction, WorkspaceActionEnvelope, apply_workspace_actions

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_WORKSPACE_HINT_RE = re.compile(
    r"\b(repo|repository|workspace|code|codebase|function|class|module|tests?|docs?)\b",
    re.IGNORECASE,
)
_PRIVATE_HINT_RE = re.compile(r"\b(private|personal|only me|just me|agent note|my note)\b", re.IGNORECASE)
_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "work": ("work", "repo", "project", "career", "business", "client", "deploy", "code"),
    "health": ("health", "fitness", "sleep", "diet", "training", "weight"),
    "deen": ("deen", "prayer", "quran", "adhkar", "islam", "ramadan"),
    "family": ("family", "wife", "marriage", "home"),
    "planning": ("plan", "planning", "schedule", "review", "goal", "task"),
}


@dataclass(slots=True)
class MemoryRoute:
    task_type: str
    scope: str
    domain: str | None
    include_private: bool = False


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain_for_agent(agent: Agent | Any) -> str | None:
    name = str(getattr(agent, "name", "") or "").strip().lower()
    if not name:
        return None
    for domain, hints in _DOMAIN_HINTS.items():
        if any(hint in name for hint in hints):
            return domain
    return None


def classify_memory_route(query: str, agent: Agent | Any) -> MemoryRoute:
    text = str(query or "").strip().lower()
    memory_scopes = {scope.strip() for scope in getattr(agent, "memory_scopes", []) if str(scope).strip()}
    shared_domains = [domain.strip() for domain in getattr(agent, "shared_domains", []) if str(domain).strip()]
    domain = None
    for candidate, hints in _DOMAIN_HINTS.items():
        if any(hint in text for hint in hints):
            domain = candidate
            break
    if domain is None and len(shared_domains) == 1:
        domain = shared_domains[0]
    if domain is None:
        domain = _domain_for_agent(agent)
    if domain and shared_domains and domain not in shared_domains:
        domain = shared_domains[0]

    if _PRIVATE_HINT_RE.search(text) and "agent_private" in memory_scopes:
        return MemoryRoute(task_type="private", scope="agent_private", domain=domain, include_private=True)
    if _WORKSPACE_HINT_RE.search(text):
        return MemoryRoute(task_type="workspace", scope="shared_global", domain=domain)
    if domain and "shared_domain" in memory_scopes:
        return MemoryRoute(task_type="domain", scope="shared_domain", domain=domain)
    return MemoryRoute(
        task_type="global",
        scope="shared_global" if "shared_global" in memory_scopes else "agent_private",
        domain=domain,
        include_private="agent_private" in memory_scopes,
    )


def _candidate_roots(route: MemoryRoute, agent: Agent | Any) -> list[Path]:
    roots: list[Path] = [obsidian_index_root()]
    if route.scope == "shared_domain" and route.domain:
        roots.append(obsidian_shared_root() / "domains" / slugify_note(route.domain))
    else:
        roots.append(obsidian_shared_root() / "global")
    if route.include_private:
        roots.append(obsidian_private_root() / "agents" / slugify_note(getattr(agent, "name", "agent")))
    return roots


def _hub_paths(route: MemoryRoute, agent: Agent | Any) -> list[Path]:
    paths: list[Path] = [obsidian_index_root() / "router.md"]
    for root in _candidate_roots(route, agent):
        index_path = root / "index.md"
        if index_path not in paths:
            paths.append(index_path)
    return paths


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


def _tokenize(query: str) -> set[str]:
    return {match.group(0).lower() for match in _WORD_RE.finditer(str(query or ""))}


def _frontmatter_domain(text: str) -> str | None:
    match = re.search(r"(?m)^domain:\s*([A-Za-z0-9_-]+)\s*$", text or "")
    if not match:
        return None
    return match.group(1).strip()


def _frontmatter_scope(text: str) -> str | None:
    match = re.search(r"(?m)^scope:\s*([A-Za-z0-9_-]+)\s*$", text or "")
    if not match:
        return None
    return match.group(1).strip()


def _frontmatter_title(text: str, fallback: str) -> str:
    heading = re.search(r"(?m)^#\s+(.+?)\s*$", text or "")
    if heading:
        return heading.group(1).strip()
    return fallback


async def _candidate_exact_hits(query: str, route: MemoryRoute, agent: Agent | Any) -> list[SharedMemorySearchHit]:
    tokens = _tokenize(query)
    if not tokens:
        return []

    scored: list[tuple[int, Path]] = []
    for root in _candidate_roots(route, agent):
        if not root.exists():
            continue
        for path in list(root.rglob("*.md"))[:80]:
            if path.name.lower() == "index.md":
                continue
            slug = path.stem.lower().replace("-", " ").replace("_", " ")
            score = sum(1 for token in tokens if token in slug)
            if score <= 0:
                continue
            scored.append((score, path))

    hits: list[SharedMemorySearchHit] = []
    for score, path in sorted(scored, key=lambda item: (-item[0], str(item[1])))[:3]:
        content = await _read_text(path)
        hits.append(
            SharedMemorySearchHit(
                title=_frontmatter_title(content, path.stem.replace("-", " ").title()),
                path=str(path),
                scope=_frontmatter_scope(content) or route.scope,
                domain=_frontmatter_domain(content) or route.domain,
                score=float(score),
                source="exact",
                snippet=content[:800].strip(),
                uri=vault_note_uri(path),
            )
        )
    return hits


async def _semantic_hits(query: str, route: MemoryRoute, agent: Agent | Any) -> list[SharedMemorySearchHit]:
    if not obsidian_vault_enabled():
        return []
    try:
        result = await openviking_client.search(
            agent_name=getattr(agent, "name", "system"),
            query=query,
            target_uri=OBSIDIAN_RESOURCE_URI,
            limit=6,
        )
    except Exception:
        return []

    hits: list[SharedMemorySearchHit] = []
    for item in result.resources[:4]:
        uri = str(item.get("uri") or "")
        if route.domain and f"/{slugify_note(route.domain)}/" not in uri and "/shared/global/" not in uri:
            continue
        hits.append(
            SharedMemorySearchHit(
                title=Path(uri).name or "Shared memory resource",
                path=uri.replace(f"{OBSIDIAN_RESOURCE_URI}/", f"{obsidian_vault_root().as_posix()}/"),
                scope=route.scope,
                domain=route.domain,
                score=float(item.get("score") or 0.0),
                source="semantic",
                snippet=str(item.get("abstract") or "").strip(),
                uri=uri,
            )
        )
    return hits


async def search_shared_memory(
    *,
    query: str,
    agent: Agent | Any,
    scope: str | None = None,
    domain: str | None = None,
) -> list[SharedMemorySearchHit]:
    if not obsidian_vault_enabled():
        return []

    route = classify_memory_route(query, agent)
    if scope:
        route.scope = scope
    if domain:
        route.domain = domain

    seen_paths: set[str] = set()
    hits: list[SharedMemorySearchHit] = []
    for hit in await _candidate_exact_hits(query, route, agent):
        if hit.path in seen_paths:
            continue
        seen_paths.add(hit.path)
        hits.append(hit)
    for hit in await _semantic_hits(query, route, agent):
        if hit.path in seen_paths:
            continue
        seen_paths.add(hit.path)
        hits.append(hit)
    return hits[:6]


async def build_shared_memory_context(
    *,
    agent: Agent | Any,
    query: str,
) -> str:
    if not obsidian_vault_enabled():
        return ""

    ensure_obsidian_vault_layout()
    route = classify_memory_route(query, agent)
    sections = [
        "[SHARED MEMORY ROUTER]",
        f"task_type: {route.task_type}",
        f"scope: {route.scope}",
        f"domain: {route.domain or 'global'}",
        f"vault_root: {obsidian_vault_root()}",
        "[END SHARED MEMORY ROUTER]",
    ]

    hub_blocks: list[str] = []
    for path in _hub_paths(route, agent):
        if not path.exists():
            continue
        content = await _read_text(path)
        if not content.strip():
            continue
        hub_blocks.append(f"PATH: {path}\n{content[:1200].strip()}")
    if hub_blocks:
        sections.append("[SHARED MEMORY HUBS]")
        sections.extend(hub_blocks[:3])
        sections.append("[END SHARED MEMORY HUBS]")

    hits = await search_shared_memory(query=query, agent=agent, scope=route.scope, domain=route.domain)
    exact_hits = [hit for hit in hits if hit.source == "exact"][:2]
    semantic_hits = [hit for hit in hits if hit.source == "semantic"][:3]

    if exact_hits:
        sections.append("[SHARED MEMORY EXACT NOTES]")
        for hit in exact_hits:
            sections.append(f"PATH: {hit.path}")
            sections.append(hit.snippet)
        sections.append("[END SHARED MEMORY EXACT NOTES]")

    if semantic_hits:
        sections.append("[SHARED MEMORY SEARCH]")
        for hit in semantic_hits:
            sections.append(f"- {hit.uri or hit.path}")
            if hit.snippet:
                sections.append(f"  {hit.snippet}")
        sections.append("[END SHARED MEMORY SEARCH]")

    return "\n".join(section for section in sections if str(section).strip())


async def _create_proposal(
    *,
    source_agent: str,
    source_session_id: int | None,
    scope: str,
    domain: str | None,
    title: str,
    target_path: Path,
    proposal_path: Path,
    expected_checksum: str | None,
    current_checksum: str | None,
    source_uri: str | None,
    proposed_content: str,
    note_metadata_json: dict[str, Any],
) -> SharedMemoryProposal:
    async with async_session() as db:
        row = SharedMemoryProposal(
            source_agent=source_agent,
            source_session_id=source_session_id,
            scope=scope,
            domain=domain,
            title=title,
            target_path=str(target_path),
            proposal_path=str(proposal_path),
            expected_checksum=expected_checksum,
            current_checksum=current_checksum,
            source_uri=source_uri,
            proposed_content=proposed_content,
            note_metadata_json=note_metadata_json,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def promote_to_shared_memory(payload) -> dict[str, Any]:
    if not obsidian_vault_enabled():
        raise ValueError("OBSIDIAN_VAULT_ROOT must be configured before promoting shared memory")

    ensure_obsidian_vault_layout()
    metadata = {
        "id": slugify_note(payload.title),
        "scope": payload.scope,
        "domain": payload.domain or ("global" if payload.scope == "shared_global" else "planning"),
        "owners": payload.owners or ["lifeos"],
        "status": payload.status,
        "managed_by": payload.managed_by,
        "source_session": payload.session_id,
        "source_uri": payload.source_uri,
        "verified_at": payload.verified_at or _now_utc(),
        "confidence": payload.confidence or "medium",
        "tags": payload.tags or ["lifeos", "shared-memory"],
    }
    note_text = render_managed_note(payload.title, payload.content, metadata)
    target_path = (
        Path(payload.target_path).resolve(strict=False)
        if payload.target_path
        else classify_note_path(
            scope=payload.scope,
            domain=payload.domain,
            agent_name=payload.agent_name,
            title=payload.title,
        )
    )

    if target_path.exists():
        current_text = await _read_text(target_path)
        current = note_checksum(current_text)
        if payload.expected_checksum and payload.expected_checksum == current:
            result = await apply_workspace_actions(
                agent_name=payload.agent_name,
                workspace_paths=[str(obsidian_vault_root())],
                envelope=WorkspaceActionEnvelope(
                    summary=f"Update shared-memory note {target_path.name}",
                    actions=[WorkspaceAction(type="write_file", path=str(target_path), content=note_text)],
                ),
            )
            return {
                "status": "updated",
                "target_path": str(target_path),
                "proposal_id": None,
                "proposal_path": None,
                "archive_entry_ids": result.archive_entry_ids or [],
                "checksum": note_checksum(note_text),
                "note_uri": vault_note_uri(target_path),
            }

        proposal_path = (
            obsidian_vault_root()
            / "inbox"
            / "proposals"
            / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{slugify_note(payload.title)}.md"
        )
        proposal_text = render_managed_note(
            f"Proposal: {payload.title}",
            (
                f"Target path: `{target_path}`\n\n"
                "Conflict detected while promoting shared memory. Review and apply manually or via API.\n\n"
                f"{payload.content}"
            ),
            metadata,
        )
        proposal_result = await apply_workspace_actions(
            agent_name=payload.agent_name,
            workspace_paths=[str(obsidian_vault_root())],
            envelope=WorkspaceActionEnvelope(
                summary=f"Create shared-memory proposal {proposal_path.name}",
                actions=[WorkspaceAction(type="write_file", path=str(proposal_path), content=proposal_text)],
            ),
        )
        proposal = await _create_proposal(
            source_agent=payload.agent_name,
            source_session_id=payload.session_id,
            scope=payload.scope,
            domain=payload.domain,
            title=payload.title,
            target_path=target_path,
            proposal_path=proposal_path,
            expected_checksum=payload.expected_checksum,
            current_checksum=current,
            source_uri=payload.source_uri,
            proposed_content=note_text,
            note_metadata_json=metadata,
        )
        return {
            "status": "conflict",
            "target_path": str(target_path),
            "proposal_id": proposal.id,
            "proposal_path": str(proposal_path),
            "archive_entry_ids": proposal_result.archive_entry_ids or [],
            "checksum": current,
            "note_uri": vault_note_uri(proposal_path),
        }

    result = await apply_workspace_actions(
        agent_name=payload.agent_name,
        workspace_paths=[str(obsidian_vault_root())],
        envelope=WorkspaceActionEnvelope(
            summary=f"Create shared-memory note {target_path.name}",
            actions=[WorkspaceAction(type="write_file", path=str(target_path), content=note_text)],
        ),
    )
    return {
        "status": "created",
        "target_path": str(target_path),
        "proposal_id": None,
        "proposal_path": None,
        "archive_entry_ids": result.archive_entry_ids or [],
        "checksum": note_checksum(note_text),
        "note_uri": vault_note_uri(target_path),
    }


async def list_shared_memory_proposals(*, status: str = "pending") -> list[SharedMemoryProposal]:
    async with async_session() as db:
        query = select(SharedMemoryProposal).order_by(SharedMemoryProposal.created_at.desc())
        if status:
            query = query.where(SharedMemoryProposal.status == status)
        result = await db.execute(query)
        return list(result.scalars().all())


async def apply_shared_memory_proposal(proposal_id: int, *, source_agent: str) -> dict[str, Any]:
    async with async_session() as db:
        row = await db.get(SharedMemoryProposal, proposal_id)
        if not row or row.status != "pending":
            raise ValueError(f"Shared-memory proposal #{proposal_id} not found")

    result = await apply_workspace_actions(
        agent_name=source_agent,
        workspace_paths=[str(obsidian_vault_root())],
        envelope=WorkspaceActionEnvelope(
            summary=f"Apply shared-memory proposal #{proposal_id}",
            actions=[WorkspaceAction(type="write_file", path=row.target_path, content=row.proposed_content)],
        ),
    )

    async with async_session() as db:
        row = await db.get(SharedMemoryProposal, proposal_id)
        if row:
            row.status = "applied"
            row.applied_at = datetime.now(timezone.utc)
            await db.commit()

    return {
        "status": "applied",
        "target_path": row.target_path,
        "proposal_id": proposal_id,
        "proposal_path": row.proposal_path,
        "archive_entry_ids": result.archive_entry_ids or [],
        "checksum": note_checksum(row.proposed_content),
        "note_uri": vault_note_uri(row.target_path),
    }


async def bootstrap_and_sync_vault() -> dict[str, Any]:
    ensure_obsidian_vault_layout()
    return await sync_obsidian_vault_resources()
