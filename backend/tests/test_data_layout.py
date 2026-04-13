from __future__ import annotations

import json

from app.config import Settings
from app.services import data_layout


def test_resolved_database_url_prefers_legacy_sqlite_when_present(tmp_path):
    legacy_root = tmp_path / "storage"
    legacy_root.mkdir(parents=True)
    legacy_db = legacy_root / "lifeos.db"
    legacy_db.write_bytes(b"sqlite")

    settings = Settings(
        _env_file=None,
        data_root=str(tmp_path / "data"),
        legacy_storage_root=str(legacy_root),
        database_url="",
    )

    assert settings.database_path == legacy_db.resolve()
    assert settings.resolved_database_url.endswith("/storage/lifeos.db")


def test_workspace_archive_root_prefers_legacy_archive_with_existing_content(tmp_path):
    legacy_archive = tmp_path / "storage" / "workspace-archive"
    legacy_archive.mkdir(parents=True)
    (legacy_archive / "existing.txt").write_text("legacy", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        data_root=str(tmp_path / "data"),
        legacy_storage_root=str(tmp_path / "storage"),
        workspace_archive_root="",
    )

    assert settings.workspace_archive_root_path == legacy_archive.resolve()


def test_ensure_data_layout_writes_manifest_under_data_root(tmp_path, monkeypatch):
    legacy_root = tmp_path / "storage"
    legacy_root.mkdir(parents=True)
    legacy_db = legacy_root / "lifeos.db"
    legacy_db.write_bytes(b"sqlite")

    settings = Settings(
        _env_file=None,
        data_root=str(tmp_path / "data"),
        legacy_storage_root=str(legacy_root),
        workspace_repo_root=str(tmp_path / "repo"),
        database_url="",
        workspace_archive_root="",
    )

    monkeypatch.setattr(data_layout, "settings", settings)

    manifest = data_layout.ensure_data_layout()
    manifest_path = settings.data_manifest_path

    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload == manifest
    assert payload["active"]["database_path"] == str(legacy_db.resolve())
    assert payload["canonical"]["database_path"] == str((tmp_path / "data" / "sqlite" / "lifeos.db").resolve())
