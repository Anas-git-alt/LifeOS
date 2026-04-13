#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

branch="${1:-$(git branch --show-current)}"
if [[ -z "$branch" ]]; then
  echo "Unable to determine the current branch."
  exit 1
fi

git_env_file="${LIFEOS_GIT_ENV_FILE:-$REPO_ROOT/.venv/.env}"
if [[ -f "$git_env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(sed 's/\r$//' "$git_env_file")
  set +a
fi

ssh_key="${LIFEOS_VPS_SSH_KEY:-/mnt/c/Users/bella/.ssh/id_ed25519}"
ssh_target="${LIFEOS_VPS_SSH_TARGET:-ubuntu@84.8.221.51}"
vps_repo="${LIFEOS_VPS_REPO:-/home/ubuntu/LifeOS}"
services=(
  openviking
  backend
  discord-bot
  webui
  tts-worker
)

if [[ ! -f "$ssh_key" ]]; then
  echo "Missing VPS SSH key at $ssh_key"
  exit 1
fi

git_push_cmd=(git push origin "$branch")
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  auth_header="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
  git_push_cmd=(git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $auth_header" push origin "$branch")
fi

echo "Pushing $branch to origin..."
"${git_push_cmd[@]}"

remote_services="${services[*]}"
echo "Deploying $branch to $ssh_target:$vps_repo ..."
ssh -i "$ssh_key" "$ssh_target" \
  "set -euo pipefail
   cd '$vps_repo'
   git config core.autocrlf false
   git fetch origin --prune
   git checkout -B '$branch' 'origin/$branch'
   git reset --hard 'origin/$branch'
   docker compose up --build -d $remote_services
   for attempt in \$(seq 1 30); do
     if curl -fsS http://127.0.0.1:8100/api/readiness >/dev/null; then
       break
     fi
     sleep 2
   done
   curl -fsS http://127.0.0.1:8100/api/readiness >/dev/null
   docker compose ps"

echo "VPS is now running branch $branch."
