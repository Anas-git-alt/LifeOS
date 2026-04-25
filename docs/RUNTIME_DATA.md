# Runtime Data Layout

Goal: keep repo clean while keeping user data safe.

## Repo rule

- Repo should only keep placeholder runtime folders:
  - `data/.gitkeep`
  - `data/README.md`
  - `storage/.gitkeep`
  - `storage/README.md`
  - `storage/init.sql`
- User runtime data should live outside repo.

## Docker Compose override

`docker-compose.yml` supports host-side runtime path overrides through a repo-root `.env` file.

Copy [compose.env.example](../compose.env.example) to `.env` and set absolute paths:

```dotenv
COMPOSE_PROJECT_NAME=lifeos-local
BACKEND_PUBLIC_PORT=8100
WEBUI_PUBLIC_PORT=3100
LIFEOS_SERVICE_ENV_FILE=.venv/.env
LIFEOS_RUNTIME_UID=1000
LIFEOS_RUNTIME_GID=1000
LIFEOS_DATA_DIR=/home/you/.lifeos-runtime/data
LIFEOS_STORAGE_DIR=/home/you/.lifeos-runtime/storage
LIFEOS_OPENVIKING_DIR=/home/you/.lifeos-runtime/storage/openviking
LIFEOS_TTS_MODEL_CACHE_DIR=/home/you/.lifeos-runtime/storage/tts-models
LIFEOS_OBSIDIAN_VAULT_DIR=/home/you/.lifeos-runtime/obsidian-vault
```

Notes:

- `.env` here is for Docker Compose host mount paths.
- `.env` can also live outside repo when you invoke Compose with `docker compose --env-file /srv/lifeos/<target>/.env ...`.
- `.venv/.env` still holds app secrets and service env vars.
- `LIFEOS_SERVICE_ENV_FILE` lets Compose load service secrets from an external file such as `/srv/lifeos/staging/.venv/.env`.
- `LIFEOS_RUNTIME_UID` and `LIFEOS_RUNTIME_GID` should match the host user that owns mounted runtime folders.
- Backend still sees `/app/data` and `/app/storage` in-container, so app behavior does not change.
- For shared-memory vault mode, set `OBSIDIAN_VAULT_ROOT=/obsidian-vault` in `.venv/.env`. Compose mounts `LIFEOS_OBSIDIAN_VAULT_DIR` there for both backend and OpenViking.

## Split VPS Conventions

Recommended compose env file for staging:

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

Recommended compose env file for prod:

```dotenv
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

## Safe migration order

1. Stop stack or accept short restart window.
2. Backup current repo-local `data/` and `storage/`.
3. Copy runtime contents to external host paths.
4. Create repo-root `.env` with the external absolute paths.
5. Restart with `docker compose up -d`.
6. Verify `docker compose ps`, `/api/health`, `/api/readiness`, and WebUI.
7. Remove migrated runtime files from repo paths, leaving only tracked placeholders.

## Script compatibility

- `scripts/backup.sh` and `scripts/verify_backup.sh` now read host override paths from repo-root `.env`.
- `scripts/runtime_path_probe.py` is the shared resolver for manifest and database paths.
