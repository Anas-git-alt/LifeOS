#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

source_branch="${1:-$(git branch --show-current)}"
if [[ -z "$source_branch" ]]; then
  echo "Unable to determine the source branch."
  exit 1
fi

if [[ "$source_branch" == "main" ]]; then
  echo "Already on main. Nothing to promote."
  exit 1
fi

echo "Publishing $source_branch before promotion..."
git push origin "$source_branch"

echo "Updating local main..."
git fetch origin --prune
git checkout main
git pull --ff-only origin main

echo "Fast-forwarding main to $source_branch..."
git merge --ff-only "$source_branch"
git push origin main

echo "Deploying main to the VPS..."
"$REPO_ROOT/scripts/deploy_vps.sh" main

echo "main now includes $source_branch and the VPS is synced to main."
