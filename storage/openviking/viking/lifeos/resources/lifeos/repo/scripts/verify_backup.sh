#!/bin/bash
# Verify backup tags and latest database integrity.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Latest backup tags:"
git tag -l "backup-*" | sort -r | head -10

if [ -f "storage/lifeos.db" ]; then
  python3 - <<'PY'
import sqlite3
conn = sqlite3.connect("storage/lifeos.db")
cur = conn.cursor()
print("db_integrity:", cur.execute("PRAGMA integrity_check").fetchone()[0])
print("agents:", cur.execute("select count(*) from agents").fetchone()[0])
print("life_items:", cur.execute("select count(*) from life_items").fetchone()[0] if cur.execute("select name from sqlite_master where type='table' and name='life_items'").fetchone() else 0)
conn.close()
PY
fi
