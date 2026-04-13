#!/bin/bash
# Verify backup tags and latest database integrity.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Latest backup tags:"
git tag -l "backup-*" | sort -r | head -10

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
print("db_integrity:", cur.execute("PRAGMA integrity_check").fetchone()[0])
print("agents:", cur.execute("select count(*) from agents").fetchone()[0])
print("life_items:", cur.execute("select count(*) from life_items").fetchone()[0] if cur.execute("select name from sqlite_master where type='table' and name='life_items'").fetchone() else 0)
print("db_path:", db_path)
conn.close()
PY
fi
