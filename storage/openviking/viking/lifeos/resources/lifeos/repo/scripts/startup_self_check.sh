#!/bin/bash
# Local startup self-check for LifeOS deployment readiness.
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".venv/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

echo "Checking required environment variables..."
required_vars=(
  "DISCORD_BOT_TOKEN"
  "DISCORD_GUILD_ID"
  "API_SECRET_KEY"
)

for var in "${required_vars[@]}"; do
  if ! grep -q "^${var}=" "$ENV_FILE"; then
    echo "Missing $var in $ENV_FILE"
    exit 1
  fi
done

if grep -q "^API_SECRET_KEY=change_me" "$ENV_FILE"; then
  echo "API_SECRET_KEY is still default placeholder"
  exit 1
fi

echo "Checking Docker services..."
docker compose config >/dev/null

echo "Startup self-check passed."
