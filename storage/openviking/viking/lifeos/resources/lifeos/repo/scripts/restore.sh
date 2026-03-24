#!/bin/bash
# LifeOS restore script - supports dry-run validation.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "Usage: ./scripts/restore.sh <tag-or-commit> [--dry-run]"
  echo ""
  echo "Recent backup tags:"
  git tag -l "backup-*" | sort -r | head -10
  exit 1
fi

TARGET="$1"
DRY_RUN="${2:-}"

if ! git rev-parse --verify "$TARGET" >/dev/null 2>&1; then
  echo "Unknown git target: $TARGET"
  exit 1
fi

if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "Dry-run restore validation for $TARGET"
  echo "Current HEAD: $(git rev-parse --short HEAD)"
  echo "Target HEAD:  $(git rev-parse --short "$TARGET")"
  git diff --name-status HEAD "$TARGET" | head -200
  echo "Dry-run complete. No files or services changed."
  exit 0
fi

echo "Restoring LifeOS to: $TARGET"
docker compose down
git checkout "$TARGET"
docker compose up --build -d
echo "Restored to $TARGET and restarted services."
