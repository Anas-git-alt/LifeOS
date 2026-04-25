# Feature Staging Playbook

This is the exact flow for testing a new feature branch without touching prod.

## Goal

Use staging for discovery and integration testing.

Use prod only after staging passes.

## One-Time VPS Baseline

Staging must already exist at:

```text
/srv/lifeos/staging/
|- app/
|- .env
|- .venv/.env
|- data/
`- storage/
```

Staging compose env must define:

```dotenv
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

Staging and prod Discord bots may run at the same time when they use separate Discord bot tokens and separate Discord servers/channels.

Never reuse the same Discord bot token in both environments. If a token is shared by mistake, fix `/srv/lifeos/staging/.venv/.env` or `/srv/lifeos/prod/.venv/.env` before starting both bots.

## Every New Feature

### 1. Work local in feature worktree

Example:

```bash
cd /home/anasbe/LifeOS-feature-next
git status --short --branch
```

### 2. Commit branch changes

If staging is ready and you want auto deploy after commit:

```bash
git add <files>
git commit -m "Describe change"
```

If you want to commit without auto deploy:

```bash
LIFEOS_SKIP_VPS_SYNC=1 git commit -m "Describe change"
```

### 3. Deploy branch to staging

```bash
./scripts/deploy_vps_staging.sh
```

Or explicit branch:

```bash
./scripts/deploy_vps_staging.sh codex/next-feature
```

What this does:

1. pushes branch to `origin`
2. SSHes to VPS
3. updates `/srv/lifeos/staging/app` to branch tip
4. runs `docker compose --env-file /srv/lifeos/staging/.env up --build -d openviking backend webui tts-worker`
5. waits for `http://127.0.0.1:18100/api/readiness`

### 4. Verify staging

On VPS:

```bash
curl -fsS http://127.0.0.1:18100/api/health
curl -fsS http://127.0.0.1:18100/api/readiness
cd /srv/lifeos/staging/app
docker compose --env-file /srv/lifeos/staging/.env ps
```

From local machine:

```bash
ssh -L 13100:127.0.0.1:13100 ubuntu@84.8.221.51
```

Then open:

- `http://127.0.0.1:13100`

If testing Discord on staging, use the staging bot token and staging Discord server configured in `/srv/lifeos/staging/.venv/.env`:

```bash
cd /srv/lifeos/staging/app
docker compose --env-file /srv/lifeos/staging/.env up -d discord-bot
```

Prod can stay online in its own server:

```bash
cd /srv/lifeos/prod/app
docker compose --env-file /srv/lifeos/prod/.env up -d discord-bot
```

### 5. Run smoke checks

Minimum:

- backend health
- backend readiness
- WebUI loads
- token login works
- one or two target user flows for branch

Optional:

- safe read-only API checks
- safe write flow if branch changes persistence

### 6. Debug if staging fails

On VPS:

```bash
cd /srv/lifeos/staging/app
docker compose --env-file /srv/lifeos/staging/.env ps
docker compose --env-file /srv/lifeos/staging/.env logs --tail=200 backend
docker compose --env-file /srv/lifeos/staging/.env logs --tail=200 webui
docker compose --env-file /srv/lifeos/staging/.env logs --tail=200 openviking
```

Common checks:

- `LIFEOS_RUNTIME_UID` and `LIFEOS_RUNTIME_GID` match `id -u ubuntu` and `id -g ubuntu`
- `/srv/lifeos/staging/data` and `/srv/lifeos/staging/storage` owned by same uid/gid
- `/srv/lifeos/staging/.env` exists
- `/srv/lifeos/staging/.venv/.env` exists

Fix ownership if needed:

```bash
sudo chown -R ubuntu:ubuntu /srv/lifeos/staging/data /srv/lifeos/staging/storage
```

### 7. Promote only after staging passes

```bash
./scripts/promote_to_main.sh
```

That pushes branch, fast-forwards `main`, pushes `main`, and deploys prod.

## Agent Rule

For new code changes:

1. edit in feature worktree
2. commit branch
3. deploy branch to staging
4. verify staging
5. promote to `main` only after staging passes

Do not use prod for discovery testing.
