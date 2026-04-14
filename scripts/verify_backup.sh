#!/bin/bash
# Verify backup tags and latest database integrity.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

echo "Latest backup tags:"
git tag -l "backup-*" | sort -r | head -10

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(sed 's/\r$//' "$REPO_ROOT/.env")
  set +a
fi

DB_PATH="$(python3 scripts/runtime_path_probe.py db)"

if [ -n "$DB_PATH" ] && [ -f "$DB_PATH" ]; then
  DB_PATH="$DB_PATH" python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

db_path = Path(os.environ["DB_PATH"])
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()
print("db_integrity:", cur.execute("PRAGMA integrity_check").fetchone()[0])
print("agents:", cur.execute("select count(*) from agents").fetchone()[0])
print("life_items:", cur.execute("select count(*) from life_items").fetchone()[0] if cur.execute("select name from sqlite_master where type='table' and name='life_items'").fetchone() else 0)
print("db_path:", db_path)
conn.close()
PY
fi
