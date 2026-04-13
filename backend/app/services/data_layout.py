"""Runtime data layout helpers and manifest writer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.config import settings


def build_data_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_this_first": str(settings.data_manifest_path),
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


def ensure_data_layout() -> dict[str, Any]:
    for path in settings.data_layout_paths:
        path.mkdir(parents=True, exist_ok=True)

    db_path = settings.database_path
    if str(db_path):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    settings.workspace_archive_root_path.mkdir(parents=True, exist_ok=True)

    manifest = build_data_manifest()
    settings.data_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
