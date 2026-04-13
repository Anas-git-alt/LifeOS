#!/usr/bin/env python3
"""Fail fast on common repo hygiene regressions."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".sh",
    ".css",
    ".html",
    ".conf",
    ".toml",
    ".txt",
}
EXACT_TEXT_FILES = {
    ".gitignore",
}
RUNTIME_PREFIXES = (
    "backend/storage/",
    "output/",
    "tmp/",
    "webui/dist/",
    "webui/node_modules/",
    "discord-bot/.pytest_cache/",
)


def _git_ls_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _is_text_path(path: Path) -> bool:
    if path.name == "Dockerfile":
        return True
    if path.name in {"requirements.txt", "package.json", "package-lock.json"}:
        return True
    if path.as_posix() in EXACT_TEXT_FILES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def main() -> int:
    tracked = _git_ls_files()
    failures: list[str] = []

    for raw in tracked:
        if raw.endswith(":Zone.Identifier"):
            failures.append(f"Tracked Windows metadata file: {raw}")
        if raw.startswith(RUNTIME_PREFIXES):
            failures.append(f"Tracked runtime/generated artifact: {raw}")

    for raw in tracked:
        path = Path(raw)
        if not _is_text_path(path):
            continue
        data = (REPO_ROOT / path).read_bytes()
        if b"\r\n" in data:
            failures.append(f"CRLF line endings detected in tracked text file: {raw}")

    required = [REPO_ROOT / ".gitattributes", REPO_ROOT / ".editorconfig"]
    for path in required:
        if not path.exists():
            failures.append(f"Missing repo hygiene contract file: {path.name}")

    if failures:
        print("repo_hygiene: FAIL")
        for item in failures:
            print(f"- {item}")
        return 1

    print("repo_hygiene: OK")
    print(f"tracked_files: {len(tracked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
