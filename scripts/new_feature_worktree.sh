#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/new_feature_worktree.sh <slug>

Example:
  ./scripts/new_feature_worktree.sh calendar-upgrade

This will:
1. refresh /home/anasbe/LifeOS-main-merge to latest origin/main
2. create branch codex/<slug>
3. create worktree /home/anasbe/LifeOS-feature-<slug>
EOF
}

slug="${1:-}"

if [[ -z "$slug" || "$slug" == "-h" || "$slug" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Invalid slug: $slug"
  echo "Use lowercase letters, numbers, and hyphens only."
  exit 1
fi

workspace_root="/home/anasbe"
main_worktree="$workspace_root/LifeOS-main-merge"
feature_worktree="$workspace_root/LifeOS-feature-$slug"
branch_name="codex/$slug"

if [[ ! -d "$main_worktree/.git" ]] && ! git -C "$main_worktree" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Missing clean main worktree at $main_worktree"
  exit 1
fi

if [[ -e "$feature_worktree" ]]; then
  echo "Target worktree path already exists: $feature_worktree"
  exit 1
fi

if git -C "$main_worktree" show-ref --verify --quiet "refs/heads/$branch_name"; then
  echo "Local branch already exists: $branch_name"
  exit 1
fi

if git -C "$main_worktree" ls-remote --exit-code --heads origin "$branch_name" >/dev/null 2>&1; then
  echo "Remote branch already exists: $branch_name"
  echo "Pick a new slug or create the worktree manually from that branch."
  exit 1
fi

echo "Refreshing clean main worktree..."
git -C "$main_worktree" fetch origin --prune
git -C "$main_worktree" checkout main
git -C "$main_worktree" pull --ff-only origin main

echo "Creating $feature_worktree on $branch_name..."
git -C "$main_worktree" worktree add "$feature_worktree" -b "$branch_name" origin/main

cat <<EOF

New feature worktree ready.
Path:   $feature_worktree
Branch: $branch_name

Next:
  cd $feature_worktree
  git status --short --branch
EOF
