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

Copy [compose.env.example](/wsl.localhost/Ubuntu/home/anasbe/LifeOS-clean/compose.env.example) to `.env` and set absolute paths:

```dotenv
LIFEOS_DATA_DIR=/home/you/.lifeos-runtime/data
LIFEOS_STORAGE_DIR=/home/you/.lifeos-runtime/storage
LIFEOS_OPENVIKING_DIR=/home/you/.lifeos-runtime/storage/openviking
LIFEOS_TTS_MODEL_CACHE_DIR=/home/you/.lifeos-runtime/storage/tts-models
```

Notes:

- `.env` here is for Docker Compose host mount paths.
- `.venv/.env` still holds app secrets and service env vars.
- Backend still sees `/app/data` and `/app/storage` in-container, so app behavior does not change.

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
