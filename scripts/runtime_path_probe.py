#!/usr/bin/env python3
"""Resolve active runtime paths whether data lives inside or outside the repo."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _host_path(raw: str, fallback: Path) -> Path:
    value = str(raw or "").strip()
    if not value:
        return fallback
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve(strict=False)


def _unique(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def _is_runtime_candidate(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    repo_tmp = (REPO_ROOT / "tmp").resolve(strict=False)
    try:
        return not (resolved == repo_tmp or resolved.is_relative_to(repo_tmp))
    except ValueError:
        return True


def _manifest_candidates() -> list[Path]:
    data_root = _host_path(os.environ.get("LIFEOS_DATA_DIR", ""), REPO_ROOT / "data")
    storage_root = _host_path(os.environ.get("LIFEOS_STORAGE_DIR", ""), REPO_ROOT / "storage")
    return _unique(
        [
            data_root / "manifest.json",
            storage_root / "manifest.json",
            REPO_ROOT / "data" / "manifest.json",
            REPO_ROOT / "storage" / "manifest.json",
        ]
    )


def _database_candidates() -> list[Path]:
    data_root = _host_path(os.environ.get("LIFEOS_DATA_DIR", ""), REPO_ROOT / "data")
    storage_root = _host_path(os.environ.get("LIFEOS_STORAGE_DIR", ""), REPO_ROOT / "storage")
    candidates: list[Path] = []
    for manifest_path in _manifest_candidates():
        if not manifest_path.exists():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for raw in (
            payload.get("active", {}).get("database_path", ""),
            payload.get("legacy", {}).get("database_path", ""),
            payload.get("canonical", {}).get("database_path", ""),
        ):
            value = str(raw or "").strip()
            if not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = (REPO_ROOT / path).resolve(strict=False)
            if _is_runtime_candidate(path):
                candidates.append(path)
    candidates.extend(
        [
            data_root / "sqlite" / "lifeos.db",
            storage_root / "lifeos.db",
            REPO_ROOT / "data" / "sqlite" / "lifeos.db",
            REPO_ROOT / "storage" / "lifeos.db",
        ]
    )
    return _unique(candidates)


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and _is_runtime_candidate(path):
            return path
    return None


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"db", "manifest"}:
        print("usage: runtime_path_probe.py [db|manifest]", file=sys.stderr)
        return 1
    mode = sys.argv[1]
    if mode == "db":
        path = _first_existing(_database_candidates())
    else:
        path = _first_existing(_manifest_candidates())
    if path is None:
        return 0
    print(path.resolve(strict=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
