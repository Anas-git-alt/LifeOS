# LifeOS Release Checklist

## Security
- [ ] `API_SECRET_KEY` is non-default.
- [ ] `DISCORD_OWNER_IDS` is configured.
- [ ] Backend and WebUI are bound to localhost (`127.0.0.1` port mappings).
- [ ] CORS origins limited to localhost.

## Reliability
- [ ] Scheduler bootstraps agent cadence jobs at startup.
- [ ] Retention prune job exists (`maintenance_prune`).
- [ ] Health and readiness endpoints return healthy/ready.

## Functional
- [ ] `!today`, `!add`, `!done`, `!miss`, `!focus`, `!profile` commands work.
- [ ] `!prayertoday`, `!prayerlog`, `!quran`, `!tahajjud`, `!adhkar` commands work.
- [ ] Approvals are owner-only in command and reaction paths.
- [ ] Prayer reaction check-ins (`✅/🕒/❌`) log correctly for reminder messages.
- [ ] WebUI Today/Life Items/Profile pages load and mutate data with token.
- [ ] `/api/prayer/weekly-summary` includes prayer accuracy, retroactive count, Quran, tahajjud, and adhkar metrics.

## Data Safety
- [ ] Backup completed with `./scripts/backup.sh`.
- [ ] Backup verified with `./scripts/verify_backup.sh`.
- [ ] Restore dry-run tested with `./scripts/restore.sh <tag> --dry-run`.

## Quality
- [ ] Backend unit tests pass in your environment.
- [ ] Docker images build successfully.
- [ ] Manual smoke test completed on Discord and WebUI.
