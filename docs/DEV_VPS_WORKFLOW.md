# LifeOS Dev And VPS Workflow

This is the staged deployment workflow for the split VPS layout.

## 1. Local Worktrees

- `/home/anasbe/LifeOS-main-merge`: clean `main` reference
- `/home/anasbe/LifeOS-feature-<task>`: active code changes
- `/home/anasbe/LifeOS-clean`: sandbox and manual testing

Develop in the feature worktree, not in the VPS checkout.

## 2. VPS Layout

Expected server structure:

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

Rules:

- staging and prod do not share database, storage, OpenViking, or vault paths
- staging and prod use different Compose project names
- staging and prod use different localhost ports
- staging defaults to no Discord bot deploy unless you explicitly opt in with a separate token
- if staging must temporarily use the prod Discord token for manual testing, stop prod `discord-bot` before starting staging `discord-bot`, then stop staging and restart prod when testing is done
- `LIFEOS_RUNTIME_UID` and `LIFEOS_RUNTIME_GID` should match `id -u ubuntu` and `id -g ubuntu` on the VPS

## 3. Required VPS Env Files

Create these files on the VPS before first deploy:

- `/srv/lifeos/staging/.env`
- `/srv/lifeos/staging/.venv/.env`
- `/srv/lifeos/prod/.env`
- `/srv/lifeos/prod/.venv/.env`

Recommended compose env values:

```dotenv
# /srv/lifeos/staging/.env
COMPOSE_PROJECT_NAME=lifeos-staging
BACKEND_PUBLIC_PORT=18100
WEBUI_PUBLIC_PORT=13100
LIFEOS_SERVICE_ENV_FILE=/srv/lifeos/staging/.venv/.env
LIFEOS_RUNTIME_UID=1001
LIFEOS_RUNTIME_GID=1001
LIFEOS_DATA_DIR=/srv/lifeos/staging/data
LIFEOS_STORAGE_DIR=/srv/lifeos/staging/storage
LIFEOS_OPENVIKING_DIR=/srv/lifeos/staging/storage/openviking
LIFEOS_TTS_MODEL_CACHE_DIR=/srv/lifeos/staging/storage/tts-models
LIFEOS_OBSIDIAN_VAULT_DIR=/srv/lifeos/staging/data/obsidian-vault
```

```dotenv
# /srv/lifeos/prod/.env
COMPOSE_PROJECT_NAME=lifeos-prod
BACKEND_PUBLIC_PORT=8100
WEBUI_PUBLIC_PORT=3100
LIFEOS_SERVICE_ENV_FILE=/srv/lifeos/prod/.venv/.env
LIFEOS_RUNTIME_UID=1001
LIFEOS_RUNTIME_GID=1001
LIFEOS_DATA_DIR=/srv/lifeos/prod/data
LIFEOS_STORAGE_DIR=/srv/lifeos/prod/storage
LIFEOS_OPENVIKING_DIR=/srv/lifeos/prod/storage/openviking
LIFEOS_TTS_MODEL_CACHE_DIR=/srv/lifeos/prod/storage/tts-models
LIFEOS_OBSIDIAN_VAULT_DIR=/srv/lifeos/prod/data/obsidian-vault
```

## 4. Deploy Commands

Staging deploys current branch by default:

```bash
./scripts/deploy_vps_staging.sh
./scripts/deploy_vps_staging.sh codex/next-feature
./scripts/deploy_vps.sh staging codex/next-feature
```

Prod deploy only accepts `main`:

```bash
./scripts/deploy_vps_prod.sh
./scripts/deploy_vps_prod.sh main
./scripts/deploy_vps.sh prod main
```

Behavior:

- every deploy pushes branch first
- staging deploy checks `http://127.0.0.1:18100/api/readiness`
- prod deploy checks `http://127.0.0.1:8100/api/readiness`
- staging default services: `openviking backend webui tts-worker`
- prod default services: `openviking backend discord-bot webui tts-worker`

If staging should run the Discord bot too, use a separate staging bot token in `/srv/lifeos/staging/.venv/.env`, then deploy with:

```bash
LIFEOS_VPS_STAGING_SERVICES="openviking backend discord-bot webui tts-worker" \
./scripts/deploy_vps_staging.sh codex/next-feature
```

## 5. Hook Behavior

`.githooks/post-commit` now deploys current branch to staging only.

Skip one automatic staging deploy:

```bash
LIFEOS_SKIP_VPS_SYNC=1 git commit -m "your message"
```

## 6. Promotion Flow

Normal flow:

1. Work in `/home/anasbe/LifeOS-feature-<task>`.
2. Commit branch.
3. Deploy branch to staging.
4. Run staging smoke tests.
5. Promote to `main`.
6. Deploy `main` to prod.
7. Run prod smoke tests.

Promotion command:

```bash
./scripts/promote_to_main.sh
```

That script:

1. pushes current feature branch
2. fast-forwards local `main`
3. pushes `main`
4. deploys `main` to prod

## 7. Smoke Checks

Staging:

```bash
curl -fsS http://127.0.0.1:18100/api/health
curl -fsS http://127.0.0.1:18100/api/readiness
```

Prod:

```bash
curl -fsS http://127.0.0.1:8100/api/health
curl -fsS http://127.0.0.1:8100/api/readiness
```

WebUI tunnel examples:

```bash
ssh -L 13100:127.0.0.1:13100 ubuntu@your-vps
ssh -L 3100:127.0.0.1:3100 ubuntu@your-vps
```

More complete migration commands live in [docs/VPS_SPLIT_MIGRATION.md](/home/anasbe/LifeOS-feature-next/docs/VPS_SPLIT_MIGRATION.md).
