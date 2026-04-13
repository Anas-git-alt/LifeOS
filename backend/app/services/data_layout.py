"""Runtime data layout helpers and manifest writer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.config import settings


def build_data_manifest(*, manifest_path: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_this_first": manifest_path,
        "active": {
            "data_root": str(settings.data_root_path),
            "database_path": str(settings.database_path),
            "database_url": settings.resolved_database_url,
            "workspace_repo_root": str(settings.workspace_repo_root_path),
            "workspace_archive_root": str(settings.workspace_archive_root_path),
            "memory_backend": settings.normalized_memory_backend,
        },
        "canonical": {
            "data_root": str(settings.data_root_path),
            "database_path": str(settings.canonical_database_path),
            "workspace_archive_root": str(settings.canonical_workspace_archive_root_path),
            "exports_root": str(settings.data_root_path / "exports"),
            "tmp_root": str(settings.data_root_path / "tmp"),
            "shared_root": str(settings.data_root_path / "shared"),
            "voices_root": str(settings.data_root_path / "voices"),
        },
        "legacy": {
            "storage_root": str(settings.legacy_storage_root_path),
            "database_path": str(settings.legacy_database_path),
            "workspace_archive_root": str(settings.legacy_workspace_archive_root_path),
        },
    }


def _best_manifest_path() -> str:
    preferred = settings.data_manifest_path
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        probe = preferred.parent / ".lifeos-write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return str(preferred)
    except OSError:
        fallback = settings.legacy_storage_root_path / "manifest.json"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return str(fallback)


def ensure_data_layout() -> dict[str, Any]:
    for path in settings.data_layout_paths:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            break

    db_path = settings.database_path
    if str(db_path):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    settings.workspace_archive_root_path.mkdir(parents=True, exist_ok=True)

    manifest_path = _best_manifest_path()
    manifest = build_data_manifest(manifest_path=manifest_path)
    manifest["manifest_path"] = manifest_path
    target_path = Path(manifest_path)
    target_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
