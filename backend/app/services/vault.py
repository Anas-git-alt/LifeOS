"""Obsidian vault bootstrap and indexing helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.openviking_client import OpenVikingApiError, openviking_client

logger = logging.getLogger(__name__)

OBSIDIAN_RESOURCE_URI = "viking://resources/lifeos/obsidian"
OBSIDIAN_INCLUDE_PATTERNS = ",".join(
    [
        "*.md",
        "*.markdown",
    ]
)
OBSIDIAN_EXCLUDE_PATTERNS = ",".join(
    [
        ".obsidian",
        ".trash",
        ".git",
    ]
)
DEFAULT_SHARED_DOMAINS = ["work", "health", "deen", "family", "planning"]
_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def obsidian_vault_enabled() -> bool:
    return settings.obsidian_vault_root_path is not None


def obsidian_vault_root() -> Path:
    root = settings.obsidian_vault_root_path
    if root is None:
        raise ValueError("OBSIDIAN_VAULT_ROOT is not configured")
    return root


def obsidian_shared_root() -> Path:
    return obsidian_vault_root() / "shared"


def obsidian_private_root() -> Path:
    return obsidian_vault_root() / "private"


def obsidian_index_root() -> Path:
    return obsidian_vault_root() / "system" / "indexes"


def obsidian_shared_index_roots() -> list[str]:
    if not obsidian_vault_enabled():
        return []
    roots = [
        obsidian_shared_root() / "global",
        obsidian_shared_root() / "domains",
        obsidian_index_root(),
    ]
    if settings.obsidian_private_namespaces_enabled:
        roots.append(obsidian_private_root())
    return [str(path.resolve(strict=False)) for path in roots]


def slugify_note(value: str, *, default: str = "note") -> str:
    cleaned = _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return cleaned or default


def note_checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def vault_note_uri(path: str | Path) -> str:
    root = obsidian_vault_root()
    resolved = Path(path).resolve(strict=False)
    relative = resolved.relative_to(root.resolve(strict=False))
    return f"{OBSIDIAN_RESOURCE_URI}/{relative.as_posix()}".rstrip("/")


def _index_template(title: str, description: str) -> str:
    stamp = datetime.now(timezone.utc).isoformat()
    return (
        "---\n"
        f"id: {slugify_note(title)}\n"
        "scope: system\n"
        "domain: indexes\n"
        "owners:\n"
        "  - lifeos\n"
        "status: active\n"
        "managed_by: lifeos\n"
        f"verified_at: {stamp}\n"
        "confidence: high\n"
        "tags:\n"
        "  - lifeos\n"
        "  - index\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{description}\n"
    )


def render_managed_note(title: str, body: str, metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key in [
        "id",
        "scope",
        "domain",
        "owners",
        "status",
        "managed_by",
        "source_session",
        "source_uri",
        "verified_at",
        "confidence",
        "tags",
    ]:
        value = metadata.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
            continue
        lines.append(f"{key}: {value}")
    lines.extend(["---", "", f"# {title}", "", str(body or "").strip(), ""])
    return "\n".join(lines)


def classify_note_path(
    *,
    scope: str,
    domain: str | None,
    agent_name: str,
    title: str,
) -> Path:
    slug = slugify_note(title)
    if scope == "shared_global":
        return obsidian_shared_root() / "global" / f"{slug}.md"
    if scope == "shared_domain":
        domain_slug = slugify_note(domain or "planning")
        return obsidian_shared_root() / "domains" / domain_slug / f"{slug}.md"
    if scope == "agent_private":
        return obsidian_private_root() / "agents" / slugify_note(agent_name) / f"{slug}.md"
    raise ValueError(f"Unsupported shared-memory scope '{scope}'")


def ensure_obsidian_vault_layout() -> dict[str, Any]:
    if not obsidian_vault_enabled():
        return {"enabled": False, "root": "", "created": []}

    root = obsidian_vault_root()
    created: list[str] = []
    warnings: list[str] = []
    directories = [
        root,
        root / "shared" / "global",
        root / "shared" / "domains",
        root / "private" / "agents",
        root / "private" / "user",
        root / "inbox" / "proposals",
        root / "system" / "indexes",
    ]
    for domain in DEFAULT_SHARED_DOMAINS:
        directories.append(root / "shared" / "domains" / domain)

    for directory in directories:
        if directory.exists():
            created.append(str(directory))
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory))
        except PermissionError:
            logger.warning("obsidian_vault_layout mkdir skipped for %s due to permissions", directory)
            warnings.append(f"mkdir:{directory}")
        except OSError as exc:
            logger.warning("obsidian_vault_layout mkdir skipped for %s: %s", directory, exc)
            warnings.append(f"mkdir:{directory}")

    seed_files: dict[Path, str] = {
        root / "shared" / "global" / "index.md": _index_template(
            "Global Shared Index",
            "Start here for durable shared facts, preferences, and cross-domain knowledge.",
        ),
        root / "private" / "user" / "index.md": _index_template(
            "User Private Index",
            "Private user notes. Do not treat as shared unless scope explicitly allows it.",
        ),
        root / "system" / "indexes" / "router.md": _index_template(
            "Memory Router",
            "Route queries into the smallest relevant scope before broad search.",
        ),
    }
    for domain in DEFAULT_SHARED_DOMAINS:
        seed_files[root / "shared" / "domains" / domain / "index.md"] = _index_template(
            f"{domain.title()} Domain Index",
            f"Shared notes for {domain}. Read this before deeper retrieval in the same domain.",
        )

    if settings.obsidian_private_namespaces_enabled:
        seed_files[root / "private" / "agents" / "index.md"] = _index_template(
            "Agent Private Index",
            "Agent-scoped notes. Read only when the requesting agent scope allows it.",
        )

    for path, content in seed_files.items():
        if path.exists():
            continue
        if not path.parent.exists():
            warnings.append(f"seed-parent-missing:{path}")
            continue
        try:
            path.write_text(content, encoding="utf-8")
        except PermissionError:
            logger.warning("obsidian_vault_layout seed skipped for %s due to permissions", path)
            warnings.append(f"seed:{path}")
        except OSError as exc:
            logger.warning("obsidian_vault_layout seed skipped for %s: %s", path, exc)
            warnings.append(f"seed:{path}")

    return {"enabled": True, "root": str(root), "created": created, "warnings": warnings}


async def sync_obsidian_vault_resources() -> dict[str, list[dict[str, str]]]:
    if not obsidian_vault_enabled() or not settings.obsidian_index_enabled:
        return {"items": []}

    ensure_obsidian_vault_layout()
    root = str(obsidian_vault_root())
    uri = OBSIDIAN_RESOURCE_URI
    items: list[dict[str, str]] = []
    try:
        await openviking_client.stat(uri)
        items.append({"path": root, "uri": uri, "status": "existing"})
        return {"items": items}
    except Exception:
        pass

    try:
        await openviking_client.add_resource(
            path=root,
            to=uri,
            reason="LifeOS Obsidian vault context",
            instruction="Index the Obsidian vault for shared-memory retrieval.",
            wait=False,
            include=OBSIDIAN_INCLUDE_PATTERNS,
            exclude=OBSIDIAN_EXCLUDE_PATTERNS,
            preserve_structure=True,
            watch_interval=5.0,
        )
        items.append({"path": root, "uri": uri, "status": "scheduled"})
    except OpenVikingApiError as exc:
        if exc.status_code != 409:
            raise
        logger.warning("Obsidian vault resource already has an active watch; replacing it")
        await openviking_client.add_resource(
            path=root,
            to=uri,
            reason="LifeOS Obsidian vault context",
            instruction="Cancel stale Obsidian vault watch before re-registering it.",
            wait=False,
            include=OBSIDIAN_INCLUDE_PATTERNS,
            exclude=OBSIDIAN_EXCLUDE_PATTERNS,
            preserve_structure=True,
            watch_interval=0,
        )
        await openviking_client.add_resource(
            path=root,
            to=uri,
            reason="LifeOS Obsidian vault context",
            instruction="Index the Obsidian vault for shared-memory retrieval.",
            wait=False,
            include=OBSIDIAN_INCLUDE_PATTERNS,
            exclude=OBSIDIAN_EXCLUDE_PATTERNS,
            preserve_structure=True,
            watch_interval=5.0,
        )
        items.append({"path": root, "uri": uri, "status": "replaced"})
    return {"items": items}
