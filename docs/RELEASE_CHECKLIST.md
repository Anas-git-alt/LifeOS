# LifeOS Release Checklist

## Security

- [ ] `API_SECRET_KEY` is non-default and not checked into git.
- [ ] `DISCORD_OWNER_IDS` is configured with real owner IDs.
- [ ] Backend and WebUI remain bound to `127.0.0.1` unless a deliberate reverse proxy setup is in place.
- [ ] Browser token usage is acceptable for the target deployment model.
- [ ] Workspace-enabled agents are scoped to the minimum required paths.

## Stack Readiness

- [ ] `docker compose ps` shows `backend`, `discord-bot`, `webui`, `openviking`, and `tts-worker` up.
- [ ] `GET /api/health` returns backend status plus OpenViking health details.
- [ ] `GET /api/readiness` returns `ready`.
- [ ] `GET /api/life/today` returns legacy agenda fields plus `scorecard`, `next_prayer`, and `rescue_plan`.
- [ ] The VPS has been tested on the feature branch that is about to be promoted.
- [ ] OpenViking legacy memory import and workspace sync complete without startup errors.
- [ ] `GET /api/tts/health` succeeds with a valid API token.

## Core Product Flows

- [ ] `!status`, `!agents`, `!today`, and `!prayertoday` work in Discord.
- [ ] Discord quick logs `!sleep`, `!meal`, `!train`, `!water`, and `!shutdown` work and return updated summary text.
- [ ] Agent chat works through Discord and WebUI.
- [ ] Session flows work end to end: create, switch, rename, clear, and history restore.
- [ ] Approvals work through both commands and emoji reactions for owner users only.
- [ ] WebUI token banner accepts the API token and protected pages load correctly.
- [ ] Mission Control shows health, approvals, jobs, today agenda, and recent agent activity.
- [ ] WebUI `Today` shows scorecard, next prayer, rescue plan, quick logs, due work, focus items, and inbox-ready items.
- [ ] WebUI quick-log buttons update same-day scorecard state without reload.
- [ ] SSE updates reach the WebUI after token exchange without manual refresh.
- [ ] Jobs can be created, edited, paused, resumed, deleted, and inspected for run logs.
- [ ] Discord natural-language job creation works with follow-up prompts when fields are missing.
- [ ] Discord one-time jobs work with `tomorrow at 9am`, `on YYYY-MM-DD at HH:MM`, and `in 10 min`.
- [ ] Discord job targeting works with both `<#channel_id>` and manual `#channel-slug` references.
- [ ] Discord natural-language agent creation queues a pending approval correctly.
- [ ] Prayer dashboard loads and prayer check-ins can be edited from WebUI.
- [ ] Quran logging and progress tracking work.
- [ ] Provider telemetry and experiment history load in WebUI.
- [ ] Voice preview works in WebUI for a speech-enabled agent.
- [ ] Discord voice join, speak, interrupt, and leave flows work if voice is part of the release scope.

## Data Safety

- [ ] Workspace archive entries are created before file mutations.
- [ ] Workspace archive restore works from WebUI or API.
- [ ] Backup completed with `./scripts/backup.sh`.
- [ ] Backup verified with `./scripts/verify_backup.sh`.
- [ ] Restore dry-run tested with `./scripts/restore.sh <tag-or-commit> --dry-run`.

## Quality

- [ ] Backend tests pass in the target environment.
- [ ] WebUI tests pass in the target environment.
- [ ] Docker images build successfully.
- [ ] Manual Discord smoke test completed.
- [ ] Manual WebUI smoke test completed.
- [ ] Manual Today accountability smoke test completed in both Discord and WebUI.
- [ ] `./scripts/promote_to_main.sh` completed and redeployed the VPS to `main`.
- [ ] Docs reviewed for the current stack and operator workflow.
