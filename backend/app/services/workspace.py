"""Workspace mutation, archival, and OpenViking context sync helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import ActionStatus, Agent, PendingAction, WorkspaceArchiveEntry
from app.services.discord_notify import send_channel_message
from app.services.events import publish_event
from app.services.openviking_client import (
    OpenVikingApiError,
    OpenVikingSearchResult,
    OpenVikingUnavailableError,
    openviking_client,
)
from app.services.runtime_state import OPENVIKING_WORKSPACE_SYNC_STATE_KEY, set_runtime_state

logger = logging.getLogger(__name__)

WORKSPACE_EVENT_TYPE = "workspace.archives.updated"
WORKSPACE_SYNC_EVENT_TYPE = "workspace.sync.updated"
WORKSPACE_ROOT_RESOURCE_URI = "viking://resources/lifeos"
WORKSPACE_REPO_RESOURCE_URI = f"{WORKSPACE_ROOT_RESOURCE_URI}/repo"
WORKSPACE_EXTERNAL_RESOURCE_URI = f"{WORKSPACE_ROOT_RESOURCE_URI}/external"
WORKSPACE_ACTIONS_START = "[WORKSPACE_ACTIONS]"
WORKSPACE_ACTIONS_END = "[/WORKSPACE_ACTIONS]"
WORKSPACE_SUMMARY_QUERY_PATTERN = re.compile(r"\b(repo|repository|workspace|project|codebase)\b", re.IGNORECASE)
_DIRECT_DELETE_PATH_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:delete|remove)\s+(?:the\s+file\s+)?(?:at\s+)?"
    r"(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)'|(\S+))\s*$",
    re.IGNORECASE,
)
_LIST_DIRECTORY_VERB_PATTERN = re.compile(
    r"\b(?:list|show|display|give|what(?:'s| is)?(?:\s+the)?|which)\b",
    re.IGNORECASE,
)
_LIST_DIRECTORY_TARGET_PATTERN = re.compile(r"\b(?:files?|contents?|entries|items?)\b", re.IGNORECASE)
_LIST_DIRECTORY_EXTENSION_PATTERN = re.compile(r"\b([A-Za-z0-9.]{1,12})\s+files?\b", re.IGNORECASE)
_QUOTED_PATH_PATTERN = re.compile(r"`([^`]+)`|\"([^\"]+)\"|'([^']+)'")
_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![\w.])(\/[A-Za-z0-9._\/-]+)")
_LABELED_DIRECTORY_PATTERN = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9._/-]*)\s+(?:folder|directory)\b", re.IGNORECASE)
_PREPOSITION_PATH_PATTERN = re.compile(
    r"\b(?:in|inside|under|within|of)\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9._/-]*)\b",
    re.IGNORECASE,
)
_WORKSPACE_LISTING_STOP_WORDS = {
    "of",
    "the",
    "this",
    "that",
    "these",
    "those",
    "workspace",
    "repo",
    "repository",
    "project",
    "codebase",
    "folder",
    "directory",
    "files",
    "contents",
    "list",
    "show",
    "display",
    "give",
    "what",
    "which",
    "all",
}
_WORKSPACE_EXTENSION_ALIASES = {
    "markdown": ".md",
    "md": ".md",
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "text": ".txt",
    "txt": ".txt",
}
OPENVIKING_IGNORE_DIRS = ",".join(
    [
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".cache",
        "dist",
        "build",
        "output",
        "tmp",
        "data",
        "coverage",
        "playwright-report",
        "test-results",
        "storage",
        "workspace-archive",
    ]
)
OPENVIKING_INCLUDE_PATTERNS = ",".join(
    [
        "*.py",
        "*.md",
        "*.txt",
        "*.json",
        "*.yaml",
        "*.yml",
        "*.js",
        "*.jsx",
        "*.ts",
        "*.tsx",
        "*.css",
        "*.html",
        "*.sql",
        "*.sh",
        "*.toml",
        "*.ini",
        "Dockerfile",
    ]
)
OPENVIKING_EXCLUDE_PATTERNS = ",".join(
    [
        "*:Zone.Identifier",
        "package-lock.json",
    ]
)


class WorkspaceAction(BaseModel):
    type: Literal["write_file", "replace_in_file", "delete_file", "restore_file"]
    path: Optional[str] = None
    content: Optional[str] = None
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    archive_entry_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_shape(self) -> "WorkspaceAction":
        if self.type in {"write_file", "replace_in_file", "delete_file"} and not self.path:
            raise ValueError(f"{self.type} requires 'path'")
        if self.type == "write_file" and self.content is None:
            raise ValueError("write_file requires 'content'")
        if self.type == "replace_in_file" and (self.old_text is None or self.new_text is None):
            raise ValueError("replace_in_file requires 'old_text' and 'new_text'")
        if self.type == "restore_file" and self.archive_entry_id is None:
            raise ValueError("restore_file requires 'archive_entry_id'")
        return self


class WorkspaceActionEnvelope(BaseModel):
    summary: str = ""
    actions: list[WorkspaceAction] = Field(default_factory=list)


@dataclass(slots=True)
class WorkspaceExecutionResult:
    notes: list[str]
    pending_action_id: int | None = None
    archive_entry_ids: list[int] | None = None


def workspace_feature_enabled() -> bool:
    return settings.openviking_enabled and settings.normalized_memory_backend == "openviking"


def default_workspace_paths() -> list[str]:
    return [str(settings.workspace_repo_root_path)]


def sanitize_workspace_paths(paths: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    raw_paths = paths or default_workspace_paths()
    for raw in raw_paths:
        value = str(raw or "").strip()
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = settings.workspace_repo_root_path / candidate
        resolved = candidate.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized or default_workspace_paths()


def compress_workspace_roots(paths: list[str]) -> list[str]:
    result: list[str] = []
    for raw in sorted(sanitize_workspace_paths(paths), key=len):
        current = Path(raw)
        if any(current == Path(existing) or current.is_relative_to(Path(existing)) for existing in result):
            continue
        result.append(str(current))
    return result


def get_agent_workspace_paths(agent) -> list[str]:
    return sanitize_workspace_paths(getattr(agent, "workspace_paths", None))


def workspace_paths_for_payload(paths: list[str] | None) -> list[str]:
    return sanitize_workspace_paths(paths)


def workspace_action_instructions(_agent_name: str, workspace_paths: list[str]) -> str:
    joined_paths = ", ".join(workspace_paths)
    return (
        "You may modify files only by appending exactly one [WORKSPACE_ACTIONS] JSON block to the end of your reply.\n"
        "Allowed paths: "
        f"{joined_paths}\n"
        "Supported actions:\n"
        '- {"type":"write_file","path":"relative/or/absolute/path","content":"full file text"}\n'
        '- {"type":"replace_in_file","path":"...","old_text":"exact existing text","new_text":"replacement text"}\n'
        '- {"type":"delete_file","path":"..."}\n'
        '- {"type":"restore_file","archive_entry_id":123}\n'
        "LifeOS automatically archives the previous version before any write, replace, restore, or delete.\n"
        "Deletes always go through the approval queue before the file is removed.\n"
        "Never claim that a file was created, updated, deleted, or restored unless you include a valid "
        "[WORKSPACE_ACTIONS] block for that change.\n"
        "If you do not include the block, explicitly say that no filesystem change has been made yet.\n"
        "Use relative paths from the repo root when possible. "
        "Do not include the block unless you actually want LifeOS to execute file changes. "
        "Keep normal human-facing explanation outside the block."
    )


def workspace_read_only_instructions(workspace_paths: list[str]) -> str:
    joined_paths = ", ".join(workspace_paths)
    return (
        "This request is read-only workspace access.\n"
        f"Allowed read scope: {joined_paths}\n"
        "Do not include [WORKSPACE_ACTIONS] for listing, reading, summarizing, or searching files.\n"
        "Do not create helper scripts, temp files, or scratch artifacts just to inspect the workspace.\n"
        "If exact file names or folder contents are provided in system context, rely on that context directly.\n"
        "If you still lack enough repo context, say so plainly instead of claiming you already changed or inspected files."
    )


def _dedupe_workspace_candidates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        cleaned = str(raw or "").strip().strip("`\"'.,:;!?()[]{}")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in _WORKSPACE_LISTING_STOP_WORDS:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _workspace_listing_candidates(user_message: str) -> list[str]:
    text = str(user_message or "")
    candidates: list[str] = []
    for match in _QUOTED_PATH_PATTERN.finditer(text):
        candidates.extend(group for group in match.groups() if group)
    for match in _ABSOLUTE_PATH_PATTERN.finditer(text):
        candidates.append(match.group(1))
    for match in _LABELED_DIRECTORY_PATTERN.finditer(text):
        candidates.append(match.group(1))
    for match in _PREPOSITION_PATH_PATTERN.finditer(text):
        candidates.append(match.group(1))
    return _dedupe_workspace_candidates(candidates)


def _workspace_listing_path_variants(raw_path: str, allowed_roots: list[Path]) -> list[str]:
    cleaned = str(raw_path or "").strip().strip("`\"'.,:;!?()[]{}")
    if not cleaned:
        return []
    variants = [cleaned]
    if cleaned.startswith("/"):
        root_strings = [str(root) for root in allowed_roots]
        if not any(cleaned == root or cleaned.startswith(f"{root}/") for root in root_strings):
            variants.append(cleaned.lstrip("/"))
    return _dedupe_workspace_candidates(variants)


def describe_workspace_listing_request(user_message: str, workspace_paths: list[str]) -> str | None:
    text = str(user_message or "").strip()
    if not text:
        return None
    if not _LIST_DIRECTORY_VERB_PATTERN.search(text) or not _LIST_DIRECTORY_TARGET_PATTERN.search(text):
        return None

    extension_match = _LIST_DIRECTORY_EXTENSION_PATTERN.search(text)
    extension_filter = None
    if extension_match:
        raw_extension = extension_match.group(1).lower().lstrip(".")
        if raw_extension and raw_extension not in _WORKSPACE_LISTING_STOP_WORDS:
            extension_filter = _WORKSPACE_EXTENSION_ALIASES.get(raw_extension, f".{raw_extension}")
    wants_files_only = bool(re.search(r"\bfiles?\b", text, re.IGNORECASE))
    allowed_roots = [Path(path).resolve() for path in sanitize_workspace_paths(workspace_paths)]

    for raw_candidate in _workspace_listing_candidates(text):
        for candidate in _workspace_listing_path_variants(raw_candidate, allowed_roots):
            try:
                _, resolved = _resolve_target_path(candidate, allowed_roots)
            except PermissionError:
                continue
            if not resolved.exists():
                continue

            target_dir = resolved if resolved.is_dir() else resolved.parent
            try:
                children = sorted(target_dir.iterdir(), key=lambda entry: (not entry.is_file(), entry.name.lower()))
            except OSError as exc:
                return f"I couldn't inspect `{_display_path(target_dir)}` because of a filesystem error: {exc}."

            labels: list[str] = []
            for child in children:
                if wants_files_only and not child.is_file():
                    continue
                if extension_filter and child.suffix.lower() != extension_filter:
                    continue
                label = _display_path(child)
                if child.is_dir():
                    label = f"{label}/"
                labels.append(f"- `{label}`")

            if not labels:
                if extension_filter:
                    descriptor = f"`{extension_filter}` files"
                elif wants_files_only:
                    descriptor = "files"
                else:
                    descriptor = "entries"
                return f"I checked `{_display_path(target_dir)}` and it has no {descriptor}."

            limited_labels = labels[:60]
            overflow_note = "\n- `...`" if len(labels) > 60 else ""
            if extension_filter:
                descriptor = f"`{extension_filter}` files"
            elif wants_files_only:
                descriptor = "files"
            else:
                descriptor = "entries"
            return (
                f"Here are the {descriptor} in `{_display_path(target_dir)}`:\n"
                f"{chr(10).join(limited_labels)}{overflow_note}"
            )

    return None


def parse_workspace_actions(response_text: str) -> tuple[str, WorkspaceActionEnvelope | None]:
    text = response_text or ""
    start = text.rfind(WORKSPACE_ACTIONS_START)
    end = text.rfind(WORKSPACE_ACTIONS_END)
    if start < 0 or end < 0 or end < start:
        return response_text, None
    raw_json = text[start + len(WORKSPACE_ACTIONS_START):end].strip()
    cleaned = f"{text[:start]}{text[end + len(WORKSPACE_ACTIONS_END):]}".strip()
    try:
        parsed = json.loads(raw_json)
        if isinstance(parsed, dict) and "actions" in parsed:
            envelope = WorkspaceActionEnvelope.model_validate(parsed)
        elif isinstance(parsed, dict) and parsed.get("type"):
            envelope = WorkspaceActionEnvelope(actions=[WorkspaceAction.model_validate(parsed)])
        elif isinstance(parsed, list):
            envelope = WorkspaceActionEnvelope(actions=[WorkspaceAction.model_validate(item) for item in parsed])
        else:
            raise ValueError("Workspace action block must be an action object, action list, or envelope")
    except (ValidationError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid workspace action block: %s", exc)
        return cleaned or response_text, None
    return cleaned, envelope


def infer_workspace_actions_from_user_message(user_message: str) -> WorkspaceActionEnvelope | None:
    text = str(user_message or "").strip()
    if not text:
        return None

    delete_match = _DIRECT_DELETE_PATH_PATTERN.match(text)
    if delete_match:
        raw_path = next((group for group in delete_match.groups() if group), "").strip()
        if raw_path:
            return WorkspaceActionEnvelope(
                summary=f"Delete `{raw_path}`",
                actions=[WorkspaceAction(type="delete_file", path=raw_path)],
            )

    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(settings.workspace_repo_root_path))
    except ValueError:
        return str(path)


def _path_hash(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def resource_uri_for_path(path: str) -> str:
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(settings.workspace_repo_root_path)
        if str(relative) in {"", "."}:
            return WORKSPACE_REPO_RESOURCE_URI
        return f"{WORKSPACE_REPO_RESOURCE_URI}/{relative.as_posix()}".rstrip("/")
    except ValueError:
        return f"{WORKSPACE_EXTERNAL_RESOURCE_URI}/{_path_hash(str(resolved))}"


def resource_prefixes_for_paths(paths: list[str]) -> list[str]:
    return [resource_uri_for_path(path) for path in sanitize_workspace_paths(paths)]


def _filter_resources(resources: list[dict], allowed_prefixes: list[str]) -> list[dict]:
    if not allowed_prefixes:
        return resources
    filtered: list[dict] = []
    for item in resources:
        uri = str(item.get("uri") or "")
        if any(uri.startswith(prefix) for prefix in allowed_prefixes):
            filtered.append(item)
    return filtered


def format_openviking_context(result: OpenVikingSearchResult, allowed_prefixes: list[str]) -> str:
    resource_hits = _filter_resources(result.resources, allowed_prefixes)[:4]
    memory_hits = list(result.memories)[:3]
    lines: list[str] = []
    if memory_hits:
        lines.append("[OPENVIKING MEMORIES]")
        for idx, item in enumerate(memory_hits, start=1):
            lines.append(f"{idx}. {item.get('abstract', '')}".strip())
            lines.append(f"   URI: {item.get('uri', '')}")
    if resource_hits:
        lines.append("[OPENVIKING RESOURCES]")
        for idx, item in enumerate(resource_hits, start=1):
            lines.append(f"{idx}. {item.get('abstract', '')}".strip())
            lines.append(f"   URI: {item.get('uri', '')}")
    if lines:
        lines.append("[END OPENVIKING CONTEXT]")
    return "\n".join(lines)


async def _read_openviking_resource_summaries(
    *,
    agent_name: str,
    workspace_paths: list[str],
    allowed_prefixes: list[str],
) -> str:
    candidate_prefixes: list[str] = []
    ignored_names = {value.strip() for value in OPENVIKING_IGNORE_DIRS.split(",") if value.strip()}
    for prefix, raw_path in zip(allowed_prefixes, sanitize_workspace_paths(workspace_paths), strict=False):
        if prefix not in candidate_prefixes:
            candidate_prefixes.append(prefix)
        root_path = Path(raw_path)
        try:
            children = sorted(root_path.iterdir(), key=lambda entry: entry.name.lower())
        except OSError:
            continue
        for child in children:
            if len(candidate_prefixes) >= 8:
                break
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in ignored_names:
                continue
            candidate_prefixes.append(f"{prefix}/{child.name}")

    lines: list[str] = []
    for prefix in candidate_prefixes[:8]:
        overview = ""
        abstract = ""
        try:
            overview = (
                await openviking_client.read_content(f"{prefix}/.overview.md", agent_name=agent_name)
            ).strip()
        except OpenVikingApiError as exc:
            if exc.status_code != 404 and (exc.code or "").upper() != "NOT_FOUND":
                logger.warning("Failed reading OpenViking overview for %s: %s", prefix, exc)
        except Exception as exc:
            logger.warning("Failed reading OpenViking overview for %s: %s", prefix, exc)
        try:
            abstract = (
                await openviking_client.read_content(f"{prefix}/.abstract.md", agent_name=agent_name)
            ).strip()
        except OpenVikingApiError as exc:
            if exc.status_code != 404 and (exc.code or "").upper() != "NOT_FOUND":
                logger.warning("Failed reading OpenViking abstract for %s: %s", prefix, exc)
        except Exception as exc:
            logger.warning("Failed reading OpenViking abstract for %s: %s", prefix, exc)

        if overview or abstract:
            lines.append("[OPENVIKING RESOURCE SUMMARY]")
            lines.append(f"URI: {prefix}")
            if abstract:
                lines.append("Abstract:")
                lines.append(abstract)
            if overview:
                lines.append("Overview:")
                lines.append(overview)
    if lines:
        lines.append("[END OPENVIKING CONTEXT]")
    return "\n".join(lines)


async def get_openviking_context(
    *,
    agent_name: str,
    query: str,
    session_id: int | None,
    workspace_paths: list[str],
) -> str:
    if not workspace_feature_enabled() or not query.strip():
        return ""
    allowed_prefixes = resource_prefixes_for_paths(workspace_paths)
    try:
        result = await openviking_client.search(
            agent_name=agent_name,
            query=query,
            session_id=session_id,
            target_uri="",
            limit=8,
        )
    except Exception as exc:
        if WORKSPACE_SUMMARY_QUERY_PATTERN.search(query):
            fallback = await _read_openviking_resource_summaries(
                agent_name=agent_name,
                workspace_paths=workspace_paths,
                allowed_prefixes=allowed_prefixes,
            )
            if fallback:
                logger.warning(
                    "OpenViking search failed for agent '%s'; using resource summaries instead: %s",
                    agent_name,
                    exc,
                )
                return fallback
        raise OpenVikingUnavailableError(f"OpenViking search failed for agent '{agent_name}': {exc}") from exc
    context = format_openviking_context(result, allowed_prefixes)
    if context:
        return context
    if WORKSPACE_SUMMARY_QUERY_PATTERN.search(query):
        return await _read_openviking_resource_summaries(
            agent_name=agent_name,
            workspace_paths=workspace_paths,
            allowed_prefixes=allowed_prefixes,
        )
    return ""


def _resolve_target_path(raw_path: str, allowed_roots: list[Path]) -> tuple[Path, Path]:
    candidate = Path(str(raw_path).strip())
    if not candidate.is_absolute():
        candidate = settings.workspace_repo_root_path / candidate
    resolved = candidate.resolve(strict=False)
    forbidden_roots = [
        settings.workspace_archive_root_path.resolve(),
        settings.data_root_path.resolve(),
        settings.legacy_storage_root_path.resolve(),
        (settings.workspace_repo_root_path / "data").resolve(strict=False),
        (settings.workspace_repo_root_path / "storage").resolve(strict=False),
        (settings.workspace_repo_root_path / "storage" / "workspace-archive").resolve(strict=False),
    ]
    if any(resolved == root or resolved.is_relative_to(root) for root in forbidden_roots):
        raise PermissionError("Runtime data directories cannot be modified through workspace actions")
    for root in allowed_roots:
        if resolved == root or resolved.is_relative_to(root):
            return root, resolved
    raise PermissionError(f"Path '{resolved}' is outside the allowed workspace roots")


async def _read_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def _write_text(path: Path, content: str) -> None:
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")


async def _delete_file(path: Path) -> None:
    await asyncio.to_thread(path.unlink)


async def _copy_file(src: Path, dst: Path) -> None:
    await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.copy2, src, dst)


async def _write_archive_blob(target_path: Path, content: bytes) -> Path:
    root = settings.workspace_archive_root_path
    stamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    archive_dir = root / stamp / uuid4().hex
    await asyncio.to_thread(archive_dir.mkdir, parents=True, exist_ok=True)
    archive_path = archive_dir / "snapshot.bin"
    await asyncio.to_thread(archive_path.write_bytes, content)
    metadata_path = archive_dir / "meta.json"
    metadata = {"target_path": str(target_path), "saved_at": _now_utc().isoformat()}
    await asyncio.to_thread(metadata_path.write_text, json.dumps(metadata, indent=2), encoding="utf-8")
    return archive_path


async def _create_archive_entry(
    *,
    agent_name: str,
    source: str,
    operation_type: str,
    status: str,
    root_path: Path,
    target_path: Path,
    details_json: dict | None = None,
    pending_action_id: int | None = None,
    restored_from_id: int | None = None,
) -> WorkspaceArchiveEntry:
    existed = target_path.exists()
    archive_path: str | None = None
    checksum_before: str | None = None
    if existed:
        content = await _read_bytes(target_path)
        checksum_before = hashlib.sha256(content).hexdigest()
        archive_path = str(await _write_archive_blob(target_path, content))

    async with async_session() as db:
        row = WorkspaceArchiveEntry(
            agent_name=agent_name,
            source=source,
            operation_type=operation_type,
            status=status,
            target_path=str(target_path),
            display_path=_display_path(target_path),
            root_path=str(root_path),
            archive_path=archive_path,
            target_existed=existed,
            checksum_before=checksum_before,
            details_json=details_json,
            pending_action_id=pending_action_id,
            restored_from_id=restored_from_id,
            resolved_at=_now_utc() if status in {"completed", "rejected", "failed", "executed"} else None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def _update_archive_entry(
    entry_id: int,
    *,
    status: str,
    pending_action_id: int | None = None,
    details_json: dict | None = None,
) -> None:
    async with async_session() as db:
        row = await db.get(WorkspaceArchiveEntry, entry_id)
        if not row:
            return
        row.status = status
        if pending_action_id is not None:
            row.pending_action_id = pending_action_id
        if details_json is not None:
            row.details_json = details_json
        row.resolved_at = _now_utc() if status in {"completed", "rejected", "failed", "executed"} else None
        await db.commit()


async def _publish_archive_update(row: WorkspaceArchiveEntry) -> None:
    await publish_event(
        WORKSPACE_EVENT_TYPE,
        {"kind": "workspace_archive", "id": str(row.id)},
        {
            "id": row.id,
            "agent_name": row.agent_name,
            "operation_type": row.operation_type,
            "status": row.status,
            "target_path": row.display_path,
            "pending_action_id": row.pending_action_id,
        },
    )


async def _maybe_notify_discord(message: str) -> None:
    channel_name = (settings.discord_audit_channel or "").strip()
    if not channel_name:
        return
    try:
        await send_channel_message(channel_name, message)
    except Exception as exc:
        logger.warning("Failed sending workspace audit message: %s", exc)


async def _finalize_row_and_notify(row: WorkspaceArchiveEntry, note: str) -> None:
    await _publish_archive_update(row)
    await _maybe_notify_discord(note)


async def apply_workspace_actions(
    *,
    agent_name: str,
    workspace_paths: list[str],
    envelope: WorkspaceActionEnvelope,
) -> WorkspaceExecutionResult:
    allowed_roots = [Path(path).resolve() for path in workspace_paths]
    notes: list[str] = []
    archive_ids: list[int] = []
    delete_entries: list[WorkspaceArchiveEntry] = []

    for action in envelope.actions:
        if action.type == "restore_file":
            restored = await restore_workspace_archive(
                action.archive_entry_id,
                source_agent=agent_name,
                source="agent",
            )
            archive_ids.append(restored.id)
            notes.append(f"Restored `{restored.display_path}` from archive #{action.archive_entry_id}.")
            continue

        root_path, target_path = _resolve_target_path(action.path or "", allowed_roots)
        if action.type == "write_file":
            row = await _create_archive_entry(
                agent_name=agent_name,
                source="agent",
                operation_type=action.type,
                status="completed",
                root_path=root_path,
                target_path=target_path,
                details_json={"content_length": len(action.content or "")},
            )
            try:
                await _write_text(target_path, action.content or "")
            except Exception as exc:
                await _update_archive_entry(row.id, status="failed", details_json={"error": str(exc)})
                raise
            archive_ids.append(row.id)
            notes.append(f"Wrote `{row.display_path}` (archive #{row.id}).")
            await _finalize_row_and_notify(row, f"[{agent_name}] wrote {row.display_path} (archive #{row.id})")
            continue

        if action.type == "replace_in_file":
            existing_text = await _read_text(target_path)
            occurrences = existing_text.count(action.old_text or "")
            if occurrences != 1:
                raise ValueError(
                    f"replace_in_file for '{target_path}' needs exactly one exact match, found {occurrences}"
                )
            row = await _create_archive_entry(
                agent_name=agent_name,
                source="agent",
                operation_type=action.type,
                status="completed",
                root_path=root_path,
                target_path=target_path,
                details_json={"old_text_length": len(action.old_text or ""), "new_text_length": len(action.new_text or "")},
            )
            try:
                updated_text = existing_text.replace(action.old_text or "", action.new_text or "", 1)
                await _write_text(target_path, updated_text)
            except Exception as exc:
                await _update_archive_entry(row.id, status="failed", details_json={"error": str(exc)})
                raise
            archive_ids.append(row.id)
            notes.append(f"Updated `{row.display_path}` (archive #{row.id}).")
            await _finalize_row_and_notify(row, f"[{agent_name}] updated {row.display_path} (archive #{row.id})")
            continue

        if action.type == "delete_file":
            if not target_path.exists() or not target_path.is_file():
                raise FileNotFoundError(f"Cannot delete missing file '{target_path}'")
            row = await _create_archive_entry(
                agent_name=agent_name,
                source="agent",
                operation_type=action.type,
                status="pending_approval",
                root_path=root_path,
                target_path=target_path,
                details_json={"requested_by": agent_name},
            )
            delete_entries.append(row)
            archive_ids.append(row.id)

    pending_action_id: int | None = None
    if delete_entries:
        async with async_session() as db:
            payload = {
                "archive_entry_ids": [row.id for row in delete_entries],
                "targets": [row.target_path for row in delete_entries],
            }
            pending = PendingAction(
                agent_name=agent_name,
                action_type="workspace_delete",
                summary=f"Delete {len(delete_entries)} file(s) from workspace",
                details=json.dumps(payload),
                status=ActionStatus.PENDING,
                risk_level="high",
            )
            db.add(pending)
            await db.commit()
            await db.refresh(pending)
            pending_action_id = pending.id
        for row in delete_entries:
            await _update_archive_entry(row.id, status="pending_approval", pending_action_id=pending_action_id)
            row.pending_action_id = pending_action_id
            await _publish_archive_update(row)
        await publish_event(
            "approvals.pending.updated",
            {"kind": "approval", "id": str(pending_action_id)},
            {"action_id": pending_action_id, "status": ActionStatus.PENDING.value, "agent_name": agent_name},
        )
        notes.append(f"Queued delete approval as action #{pending_action_id}.")

    return WorkspaceExecutionResult(notes=notes, pending_action_id=pending_action_id, archive_entry_ids=archive_ids)


async def execute_workspace_delete_action(action: PendingAction) -> tuple[bool, str]:
    try:
        payload = json.loads(action.details or "{}")
    except json.JSONDecodeError as exc:
        return False, f"Invalid workspace delete payload: {exc}"

    entry_ids = [int(value) for value in (payload.get("archive_entry_ids") or [])]
    if not entry_ids:
        return False, "No workspace archive entries were supplied"

    deleted = 0
    async with async_session() as db:
        result = await db.execute(
            select(WorkspaceArchiveEntry).where(WorkspaceArchiveEntry.id.in_(entry_ids))
        )
        rows = list(result.scalars().all())
        if len(rows) != len(entry_ids):
            return False, "One or more workspace archive entries were not found"
        for row in rows:
            target = Path(row.target_path)
            try:
                if target.exists():
                    await _delete_file(target)
                row.status = "executed"
                row.resolved_at = _now_utc()
                deleted += 1
            except Exception as exc:
                row.status = "failed"
                row.resolved_at = _now_utc()
                row.details_json = {**(row.details_json or {}), "error": str(exc)}
                await db.commit()
                return False, f"Failed deleting {row.display_path}: {exc}"
        await db.commit()

    for row in rows:
        await _publish_archive_update(row)
    await _maybe_notify_discord(f"[{action.agent_name}] approved deletion of {deleted} file(s)")
    return True, f"Deleted {deleted} file(s)"


async def reject_workspace_delete_action(action_id: int, reason: str = "") -> None:
    async with async_session() as db:
        result = await db.execute(
            select(WorkspaceArchiveEntry).where(WorkspaceArchiveEntry.pending_action_id == action_id)
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.status = "rejected"
            row.resolved_at = _now_utc()
            row.details_json = {**(row.details_json or {}), "rejection_reason": reason}
        await db.commit()
    for row in rows:
        await _publish_archive_update(row)


async def list_workspace_archives(
    *,
    agent_name: str | None = None,
    limit: int = 100,
) -> list[WorkspaceArchiveEntry]:
    async with async_session() as db:
        query = select(WorkspaceArchiveEntry).order_by(WorkspaceArchiveEntry.created_at.desc()).limit(limit)
        if agent_name:
            query = query.where(WorkspaceArchiveEntry.agent_name == agent_name)
        result = await db.execute(query)
        return list(result.scalars().all())


async def restore_workspace_archive(
    archive_entry_id: int,
    *,
    source_agent: str,
    source: str = "api",
) -> WorkspaceArchiveEntry:
    async with async_session() as db:
        row = await db.get(WorkspaceArchiveEntry, archive_entry_id)
        if not row:
            raise ValueError(f"Workspace archive #{archive_entry_id} not found")
        if not row.archive_path:
            raise ValueError(f"Workspace archive #{archive_entry_id} has no restorable snapshot")

    root_path = Path(row.root_path).resolve()
    target_path = Path(row.target_path).resolve()
    archive_path = Path(row.archive_path).resolve()
    restore_entry = await _create_archive_entry(
        agent_name=source_agent,
        source=source,
        operation_type="restore_file",
        status="completed",
        root_path=root_path,
        target_path=target_path,
        restored_from_id=row.id,
        details_json={"restored_from_id": row.id},
    )
    try:
        await _copy_file(archive_path, target_path)
    except Exception as exc:
        await _update_archive_entry(restore_entry.id, status="failed", details_json={"error": str(exc)})
        raise
    await _finalize_row_and_notify(
        restore_entry,
        f"[{source_agent}] restored {restore_entry.display_path} from archive #{archive_entry_id}",
    )
    return restore_entry


async def _collect_workspace_sync_paths() -> list[str]:
    paths = default_workspace_paths()
    async with async_session() as db:
        result = await db.execute(select(Agent).order_by(Agent.id))
        for agent in result.scalars().all():
            paths.extend(get_agent_workspace_paths(agent))
    return compress_workspace_roots(paths)


async def sync_workspace_resources(paths: list[str] | None = None) -> dict[str, list[dict[str, str]]]:
    if not workspace_feature_enabled():
        return {"items": []}

    unique_roots = compress_workspace_roots(paths or await _collect_workspace_sync_paths())
    items: list[dict[str, str]] = []
    for path in unique_roots:
        uri = resource_uri_for_path(path)
        try:
            await openviking_client.stat(uri)
            items.append({"path": path, "uri": uri, "status": "existing"})
            continue
        except Exception:
            pass

        try:
            await openviking_client.add_resource(
                path=path,
                to=uri,
                reason="LifeOS workspace context",
                instruction="Index this workspace for LifeOS agent retrieval.",
                wait=False,
                ignore_dirs=OPENVIKING_IGNORE_DIRS,
                include=OPENVIKING_INCLUDE_PATTERNS,
                exclude=OPENVIKING_EXCLUDE_PATTERNS,
                preserve_structure=True,
                watch_interval=5.0,
            )
            items.append({"path": path, "uri": uri, "status": "scheduled"})
        except OpenVikingApiError as exc:
            if exc.status_code != 409:
                raise
            logger.warning("Workspace resource %s already has an active watch; replacing it", uri)
            await openviking_client.add_resource(
                path=path,
                to=uri,
                reason="LifeOS workspace context",
                instruction="Cancel stale workspace watch before re-registering it.",
                wait=False,
                ignore_dirs=OPENVIKING_IGNORE_DIRS,
                include=OPENVIKING_INCLUDE_PATTERNS,
                exclude=OPENVIKING_EXCLUDE_PATTERNS,
                preserve_structure=True,
                watch_interval=0,
            )
            await openviking_client.add_resource(
                path=path,
                to=uri,
                reason="LifeOS workspace context",
                instruction="Index this workspace for LifeOS agent retrieval.",
                wait=False,
                ignore_dirs=OPENVIKING_IGNORE_DIRS,
                include=OPENVIKING_INCLUDE_PATTERNS,
                exclude=OPENVIKING_EXCLUDE_PATTERNS,
                preserve_structure=True,
                watch_interval=5.0,
            )
            items.append({"path": path, "uri": uri, "status": "replaced"})

    await publish_event(
        WORKSPACE_SYNC_EVENT_TYPE,
        {"kind": "workspace_sync", "id": "context"},
        {"items": items},
    )
    await set_runtime_state(
        OPENVIKING_WORKSPACE_SYNC_STATE_KEY,
        {
            "status": "completed",
            "synced_at": _now_utc().isoformat(),
            "item_count": len(items),
            "items": items,
        },
    )
    return {"items": items}
