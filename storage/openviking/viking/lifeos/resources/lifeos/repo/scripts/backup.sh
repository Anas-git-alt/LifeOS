#!/bin/bash
# LifeOS backup script - commit, tag, and push with lightweight DB verification.
set -euo pipefail

cd "$(dirname "$0")/.."

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BRANCH="main"

echo "LifeOS Backup - $TIMESTAMP"

if [ -f "storage/lifeos.db" ]; then
  python3 - <<'PY'
import sqlite3
conn = sqlite3.connect("storage/lifeos.db")
cur = conn.cursor()
result = cur.execute("PRAGMA integrity_check").fetchone()[0]
conn.close()
if result != "ok":
    raise SystemExit(f"Database integrity check failed: {result}")
print("Database integrity check: ok")
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
