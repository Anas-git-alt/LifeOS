#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/deploy_vps.sh [staging|prod] [branch]
  ./scripts/deploy_vps.sh [branch]

Defaults:
  staging target defaults to current branch
  prod target defaults to main and only allows main
EOF
}

target="${1:-staging}"
branch_arg="${2:-}"

case "$target" in
  staging|prod)
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    branch_arg="$target"
    target="staging"
    ;;
esac

if [[ -n "$branch_arg" ]]; then
  branch="$branch_arg"
elif [[ "$target" == "prod" ]]; then
  branch="main"
else
  branch="$(git branch --show-current)"
fi

if [[ -z "$branch" ]]; then
  echo "Unable to determine deployment branch."
  exit 1
fi

if [[ "$target" == "prod" && "$branch" != "main" ]]; then
  echo "Prod deploy only allowed for main. Refusing branch: $branch"
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

case "$target" in
  staging)
    deploy_root="${LIFEOS_VPS_STAGING_ROOT:-/srv/lifeos/staging}"
    vps_repo="${LIFEOS_VPS_STAGING_REPO:-$deploy_root/app}"
    compose_env_file="${LIFEOS_VPS_STAGING_COMPOSE_ENV_FILE:-$deploy_root/.env}"
    readiness_url="${LIFEOS_VPS_STAGING_READINESS_URL:-http://127.0.0.1:18100/api/readiness}"
    services_string="${LIFEOS_VPS_STAGING_SERVICES:-openviking backend webui tts-worker}"
    ;;
  prod)
    deploy_root="${LIFEOS_VPS_PROD_ROOT:-/srv/lifeos/prod}"
    vps_repo="${LIFEOS_VPS_PROD_REPO:-$deploy_root/app}"
    compose_env_file="${LIFEOS_VPS_PROD_COMPOSE_ENV_FILE:-$deploy_root/.env}"
    readiness_url="${LIFEOS_VPS_PROD_READINESS_URL:-http://127.0.0.1:8100/api/readiness}"
    services_string="${LIFEOS_VPS_PROD_SERVICES:-openviking backend discord-bot webui tts-worker}"
    ;;
esac

shared_root="${LIFEOS_VPS_SHARED_ROOT:-/srv/lifeos/shared}"
read -r -a services <<< "$services_string"

if [[ ! -f "$ssh_key" ]]; then
  echo "Missing VPS SSH key at $ssh_key"
  exit 1
fi

ssh_cmd=(ssh)
ssh_key_arg="$ssh_key"
if [[ "$ssh_key" == /mnt/c/* ]] && command -v ssh.exe >/dev/null 2>&1; then
  ssh_cmd=(ssh.exe)
  ssh_key_arg="$(wslpath -w "$ssh_key")"
fi

git_push_cmd=(git push origin "$branch")
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  auth_header="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
  git_push_cmd=(git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $auth_header" push origin "$branch")
fi

echo "Pushing $branch to origin..."
"${git_push_cmd[@]}"

echo "Deploy target: $target"
echo "Remote app dir: $vps_repo"
echo "Compose env file: $compose_env_file"
echo "Readiness check: $readiness_url"
echo "Services: ${services[*]}"

"${ssh_cmd[@]}" -i "$ssh_key_arg" "$ssh_target" bash -s -- \
  "$branch" \
  "$vps_repo" \
  "$compose_env_file" \
  "$readiness_url" \
  "$shared_root" \
  "${services[@]}" <<'EOF'
set -euo pipefail

branch="$1"
shift
vps_repo="$1"
shift
compose_env_file="$1"
shift
readiness_url="$1"
shift
shared_root="$1"
shift
services=("$@")

deploy_root="$(dirname "$vps_repo")"

mkdir -p \
  "$deploy_root/data" \
  "$deploy_root/storage" \
  "$deploy_root/backups" \
  "$deploy_root/.venv" \
  "$shared_root/deploy-logs" \
  "$shared_root/snapshots"

if [[ ! -d "$vps_repo/.git" ]]; then
  echo "Missing git repo at $vps_repo"
  exit 1
fi

if [[ ! -f "$compose_env_file" ]]; then
  echo "Missing compose env file at $compose_env_file"
  exit 1
fi

cd "$vps_repo"
git config core.autocrlf false
git fetch origin --prune
git checkout -B "$branch" "origin/$branch"
git reset --hard "origin/$branch"
docker compose --env-file "$compose_env_file" config >/dev/null
docker compose --env-file "$compose_env_file" up --build -d "${services[@]}"

for attempt in $(seq 1 30); do
  if curl -fsS "$readiness_url" >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS "$readiness_url" >/dev/null
docker compose --env-file "$compose_env_file" ps
EOF

echo "VPS target $target now runs branch $branch."
