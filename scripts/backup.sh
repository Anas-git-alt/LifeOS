#!/bin/bash
# LifeOS backup script - commit, tag, and push with lightweight DB verification.
set -euo pipefail

cd "$(dirname "$0")/.."

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BRANCH="main"

echo "LifeOS Backup - $TIMESTAMP"

DB_PATH=$(python3 - <<'PY'
from pathlib import Path
import json

candidates = []
manifest_path = Path("data/manifest.json")
if manifest_path.exists():
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidates.append(payload.get("active", {}).get("database_path", ""))
        candidates.append(payload.get("legacy", {}).get("database_path", ""))
    except Exception:
        pass
candidates.extend(["data/sqlite/lifeos.db", "storage/lifeos.db"])
for raw in candidates:
    value = str(raw or "").strip()
    if value and Path(value).exists():
        print(value)
        break
PY
)

if [ -n "$DB_PATH" ] && [ -f "$DB_PATH" ]; then
  DB_PATH="$DB_PATH" python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

db_path = Path(os.environ["DB_PATH"])
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()
result = cur.execute("PRAGMA integrity_check").fetchone()[0]
conn.close()
if result != "ok":
    raise SystemExit(f"Database integrity check failed: {result}")
print(f"Database integrity check: ok ({db_path})")
PY
fi

if [ -z "$(git status --porcelain)" ]; then
  echo "No changes to commit."
  exit 0
fi

git add -A

if git diff --cached --name-only | grep -qE '(^|/)\.env$|\.env\.local$|\.venv/'; then
  echo "ABORT: secret file detected in staged changes."
  exit 1
fi

git commit -m "backup: auto-commit $TIMESTAMP"
git tag "backup-$TIMESTAMP"

if [ -n "$(git remote -v)" ]; then
  git push origin "$BRANCH" --tags
  echo "Pushed to remote branch $BRANCH with backup tag."
else
  echo "No remote configured, local backup tag created only."
fi
