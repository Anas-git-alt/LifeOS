# LifeOS VPS Split Migration

This runbook migrates the VPS from one repo path and one stack to separate staging and prod stacks.

## 1. Target Layout

```text
/srv/lifeos/
|- staging/
|  |- app/
|  |- .env
|  |- .venv/.env
|  |- data/
|  |- storage/
|  `- backups/
|- prod/
|  |- app/
|  |- .env
|  |- .venv/.env
|  |- data/
|  |- storage/
|  `- backups/
`- shared/
   |- deploy-logs/
   `- snapshots/
```

Non-negotiable isolation:

- staging and prod do not share DB files
- staging and prod do not share storage
- staging and prod do not share OpenViking data
- staging and prod do not share runtime vault paths

## 2. Prepare Folders On VPS

```bash
sudo mkdir -p \
  /srv/lifeos/staging/app \
  /srv/lifeos/staging/.venv \
  /srv/lifeos/staging/data \
  /srv/lifeos/staging/storage \
  /srv/lifeos/staging/backups \
  /srv/lifeos/prod/app \
  /srv/lifeos/prod/.venv \
  /srv/lifeos/prod/data \
  /srv/lifeos/prod/storage \
  /srv/lifeos/prod/backups \
  /srv/lifeos/shared/deploy-logs \
  /srv/lifeos/shared/snapshots

sudo chown -R ubuntu:ubuntu /srv/lifeos
```

## 3. Clone Repo Into Staging And Prod

Run this first for staging:

```bash
git clone <your-origin-url> /srv/lifeos/staging/app
```

Keep old prod at `/home/ubuntu/LifeOS` during transition.

After staging is stable, clone real prod:

```bash
git clone <your-origin-url> /srv/lifeos/prod/app
```

## 4. Create Compose Env Files

Staging compose env:

```bash
cat >/srv/lifeos/staging/.env <<'EOF'
COMPOSE_PROJECT_NAME=lifeos-staging
BACKEND_PUBLIC_PORT=18100
WEBUI_PUBLIC_PORT=13100
LIFEOS_SERVICE_ENV_FILE=/srv/lifeos/staging/.venv/.env
LIFEOS_DATA_DIR=/srv/lifeos/staging/data
LIFEOS_STORAGE_DIR=/srv/lifeos/staging/storage
LIFEOS_OPENVIKING_DIR=/srv/lifeos/staging/storage/openviking
LIFEOS_TTS_MODEL_CACHE_DIR=/srv/lifeos/staging/storage/tts-models
LIFEOS_OBSIDIAN_VAULT_DIR=/srv/lifeos/staging/data/obsidian-vault
EOF
```

Prod compose env:

```bash
cat >/srv/lifeos/prod/.env <<'EOF'
COMPOSE_PROJECT_NAME=lifeos-prod
BACKEND_PUBLIC_PORT=8100
WEBUI_PUBLIC_PORT=3100
LIFEOS_SERVICE_ENV_FILE=/srv/lifeos/prod/.venv/.env
LIFEOS_DATA_DIR=/srv/lifeos/prod/data
LIFEOS_STORAGE_DIR=/srv/lifeos/prod/storage
LIFEOS_OPENVIKING_DIR=/srv/lifeos/prod/storage/openviking
LIFEOS_TTS_MODEL_CACHE_DIR=/srv/lifeos/prod/storage/tts-models
LIFEOS_OBSIDIAN_VAULT_DIR=/srv/lifeos/prod/data/obsidian-vault
EOF
```

## 5. Create Service Secret Files

Copy current app secrets, then edit per target:

```bash
cp /home/ubuntu/LifeOS/.venv/.env /srv/lifeos/staging/.venv/.env
cp /home/ubuntu/LifeOS/.venv/.env /srv/lifeos/prod/.venv/.env
```

Then update:

- staging ports stay in `/srv/lifeos/staging/.env`, not here
- staging bot should use separate token or stay disabled
- prod keeps real prod token and secrets
- `DATABASE_URL` stays container-local, for example `sqlite+aiosqlite:////app/storage/lifeos.db`
- `OBSIDIAN_VAULT_ROOT=/obsidian-vault` if vault mount used

Staging safest default: do not run `discord-bot` service.

## 6. Bring Up Staging First

Deploy feature branch to staging:

```bash
cd /srv/lifeos/staging/app
git fetch origin --prune
git checkout -B codex/next-feature origin/codex/next-feature
git reset --hard origin/codex/next-feature
docker compose --env-file /srv/lifeos/staging/.env up --build -d openviking backend webui tts-worker
curl -fsS http://127.0.0.1:18100/api/health
curl -fsS http://127.0.0.1:18100/api/readiness
docker compose --env-file /srv/lifeos/staging/.env ps
```

Equivalent local command from feature worktree:

```bash
./scripts/deploy_vps_staging.sh codex/next-feature
```

## 7. Staging Verification

Check:

```bash
curl -fsS http://127.0.0.1:18100/api/health
curl -fsS http://127.0.0.1:18100/api/readiness
```

Then verify:

- WebUI through `127.0.0.1:13100`
- login token works
- main read-only flows work
- one or two safe write flows work
- staging Discord bot remains off unless separate token configured

Reverse proxy options:

- `staging.example.com` -> `127.0.0.1:13100`
- `example.com` -> `127.0.0.1:3100`
- or `/staging/` path split if your proxy config already supports it

## 8. Create Real Prod After Staging Passes

Do not touch old `/home/ubuntu/LifeOS` until new prod is healthy.

Bring up new prod:

```bash
cd /srv/lifeos/prod/app
git fetch origin --prune
git checkout -B main origin/main
git reset --hard origin/main
docker compose --env-file /srv/lifeos/prod/.env up --build -d
curl -fsS http://127.0.0.1:8100/api/health
curl -fsS http://127.0.0.1:8100/api/readiness
docker compose --env-file /srv/lifeos/prod/.env ps
```

Equivalent local command:

```bash
./scripts/deploy_vps_prod.sh main
```

## 9. Cut Over Reverse Proxy

Only after prod checks pass, switch proxy to new prod ports.

Example backend targets:

- staging backend: `127.0.0.1:18100`
- prod backend: `127.0.0.1:8100`

Example web targets:

- staging webui: `127.0.0.1:13100`
- prod webui: `127.0.0.1:3100`

## 10. Retire Old Single-Path Deploy

After new prod stable:

```bash
mv /home/ubuntu/LifeOS /home/ubuntu/LifeOS-rollback-archive-$(date +%F)
```

Keep it only as rollback/archive until confidence is high.

## 11. Normal Ongoing Commands

Feature to staging:

```bash
./scripts/deploy_vps_staging.sh codex/next-feature
```

Main to prod:

```bash
./scripts/deploy_vps_prod.sh main
```

Promote feature branch to prod:

```bash
./scripts/promote_to_main.sh
```
