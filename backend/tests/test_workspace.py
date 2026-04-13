from __future__ import annotations

from pathlib import Path

from app.services.workspace import describe_workspace_listing_request


def test_describe_workspace_listing_request_lists_markdown_files(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "README.md").write_text("# Docs\n", encoding="utf-8")
    (docs_dir / "guide.md").write_text("Guide\n", encoding="utf-8")
    (docs_dir / "draft.txt").write_text("ignore\n", encoding="utf-8")

    monkeypatch.setattr("app.services.workspace.settings.workspace_repo_root", str(tmp_path))
    monkeypatch.setattr("app.services.workspace.settings.workspace_archive_root", str(tmp_path / "archive"))

    response = describe_workspace_listing_request(
        "what is the list of md files that are in /docs folder",
        [str(tmp_path)],
    )

    assert response is not None
    assert "Here are the `.md` files in `docs`" in response
    assert "`docs/README.md`" in response
    assert "`docs/guide.md`" in response
    assert "`docs/draft.txt`" not in response
