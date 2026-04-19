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

git_env_file="${LIFEOS_GIT_ENV_FILE:-$REPO_ROOT/.venv/.env}"
if [[ -f "$git_env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(sed 's/\r$//' "$git_env_file")
  set +a
fi

git_push_cmd=(git push origin)
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  auth_header="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
  git_push_cmd=(git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $auth_header" push origin)
fi

echo "Publishing $source_branch before promotion..."
"${git_push_cmd[@]}" "$source_branch"

echo "Updating local main..."
git fetch origin --prune
git checkout main
git pull --ff-only origin main

echo "Fast-forwarding main to $source_branch..."
git merge --ff-only "$source_branch"
"${git_push_cmd[@]}" main

echo "Deploying main to the VPS..."
"$REPO_ROOT/scripts/deploy_vps_prod.sh" main

echo "main now includes $source_branch and the VPS is synced to main."
