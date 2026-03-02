# LifeOS Local Production Runbook

## 1) Preflight
1. Copy `.env.example` to `.venv/.env`.
2. Set `API_SECRET_KEY` to a strong random value.
3. Set `DISCORD_OWNER_IDS` to your Discord user ID.
4. Run `./scripts/startup_self_check.sh`.

## 2) Start
1. `docker compose up --build -d`
2. Verify:
   - `curl http://localhost:8100/api/health`
   - `curl http://localhost:8100/api/readiness`
   - Open `http://localhost:3100`
3. In WebUI, paste your token (`API_SECRET_KEY`) in the token banner once.

Port overrides (optional):
- `BACKEND_PUBLIC_PORT=8200 WEBUI_PUBLIC_PORT=3200 docker compose up --build -d`
- `COMPOSE_PROJECT_NAME=lifeos-v1-2 docker compose up --build -d`

## 3) Daily Ops
1. Check status in Discord with `!status`.
2. Review pending approvals via `!pending`.
3. Review focus agenda via `!today` or WebUI Today page.
4. Verify prayer schedule with `!prayertoday`.
5. Check weekly deen metrics with `GET /api/prayer/weekly-summary` (token required).

## 4) Backup and Restore
1. Manual backup: `./scripts/backup.sh`
2. Verify backup: `./scripts/verify_backup.sh`
3. Dry-run restore: `./scripts/restore.sh backup-YYYY-MM-DD_HH-MM-SS --dry-run`
4. Actual restore: `./scripts/restore.sh backup-YYYY-MM-DD_HH-MM-SS`

## 5) Troubleshooting
1. `docker compose logs -f backend`
2. `docker compose logs -f discord-bot`
3. If token auth errors in WebUI, re-save token in token banner.
4. If scheduler stops, restart backend container.
5. If prayer reminders are missing:
   - Verify profile city/country/timezone in `!profile`
   - Verify `DISCORD_OWNER_IDS` includes your user ID
   - Check `GET /api/prayer/schedule/today` and `GET /api/prayer/due-reminders`
