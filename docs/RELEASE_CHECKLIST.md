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
- [ ] Session commands work: `!sessions`, `!newsession`, `!usesession`, `!renamesession`, `!clearsession`, `!history`.
- [ ] `!ask` and `!sandbox` keep context in the active session per user/channel/agent.
- [ ] `!prayertoday`, `!prayerlog`, `!quran`, `!tahajjud`, `!adhkar` commands work.
- [ ] Approvals are owner-only in command and reaction paths.
- [ ] Prayer reaction check-ins (`✅/🕒/❌`) log correctly for reminder messages.
- [ ] WebUI Today/Life Items/Profile pages load and mutate data with token.
- [ ] WebUI agent Chat tab supports create/switch/rename/clear session and message history restore.
- [ ] `/api/agents/{agent}/sessions*` endpoints work end-to-end.
- [ ] `/api/prayer/weekly-summary` includes prayer accuracy, retroactive count, Quran, tahajjud, and adhkar metrics.
- [ ] `data_start_date` can be updated via `/api/settings/` and WebUI Settings page.
- [ ] Reports/analytics ignore records older than `data_start_date` without deleting raw rows.
- [ ] Jobs UI + API support list/create/edit/pause/resume/delete and run logs.
- [ ] Discord NL flows (`!schedule`, `!spawnagent`) ask follow-ups when required fields are missing.
- [ ] Approving NL-created actions executes create-job/create-agent and records audit trail.

## Data Safety
- [ ] Backup completed with `./scripts/backup.sh`.
- [ ] Backup verified with `./scripts/verify_backup.sh`.
- [ ] Restore dry-run tested with `./scripts/restore.sh <tag> --dry-run`.

## Quality
- [ ] Backend unit tests pass in your environment.
- [ ] Docker images build successfully.
- [ ] Manual smoke test completed on Discord and WebUI.
