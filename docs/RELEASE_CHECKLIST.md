# LifeOS Release Checklist

## Security

- [ ] `API_SECRET_KEY` is non-default and not checked into git.
- [ ] `DISCORD_OWNER_IDS` is configured with real owner IDs.
- [ ] Backend and WebUI remain bound to `127.0.0.1` unless a deliberate reverse proxy setup is in place.
- [ ] Browser token usage is acceptable for the target deployment model.
- [ ] Workspace-enabled agents are scoped to the minimum required paths.

## Stack Readiness

- [x] `docker compose ps` shows `backend`, `discord-bot`, `webui`, `openviking`, and `tts-worker` up.
- [x] `GET /api/health` returns backend status plus OpenViking health details.
- [x] `GET /api/readiness` returns `ready`.
- [x] `GET /api/life/today` returns legacy agenda fields plus `scorecard`, `next_prayer`, `rescue_plan`, `sleep_protocol`, `streaks`, and `trend_summary`.
- [x] The VPS has been tested on the feature branch that is about to be promoted.
- [ ] OpenViking legacy memory import and workspace sync complete without startup errors.
- [x] `GET /api/tts/health` succeeds with a valid API token.

## Core Product Flows

- [ ] `!agents` and `!prayertoday` work in Discord.
- [x] `!status` works in Discord on the live server.
- [x] `!today` works in Discord on the live server.
- [x] Local/VPS automated coverage exists for Discord smoke commands `!status`, `!agents`, `!today`, plus warning-note handling.
- [x] Discord quick logs `!sleep`, `!meal`, `!train`, `!water`, `!family`, `!priority`, and `!shutdown` are implemented and covered locally.
- [x] Discord quick logs `!sleep`, `!meal`, `!train`, `!water`, and `!shutdown` work and return updated summary text on the live server.
- [x] Discord commitment capture `!commit` and `!commitfollow` are implemented and covered locally.
- [x] Discord commitment capture promotes ready commitments, keeps clarifying commitments in Inbox, and creates linked reminders.
- [x] Discord commitment follow-up by inbox id works on staging and avoids duplicate Life items for the same inbox/session.
- [x] Discord commitment deadlines support `today eod` and `tomorrow end of day`.
- [x] Discord `!snooze`, `!focuscoach`, and `!commitreview` are implemented and covered locally.
- [x] Weekly commitment review is scheduled for Sunday 10:00 in `#weekly-review`.
- [ ] Agent chat works through Discord and WebUI.
- [ ] Session flows work end to end: create, switch, rename, clear, and history restore.
- [ ] Approvals work through both commands and emoji reactions for owner users only.
- [x] WebUI token banner accepts the API token and protected pages load correctly.
- [ ] Mission Control shows health, approvals, jobs, today agenda, and recent agent activity.
- [x] WebUI `Today` scorecard, next prayer, rescue plan, sleep protocol, streaks, trend summary, quick logs, due work, focus items, and inbox-ready layout are implemented and covered locally.
- [x] WebUI `Today` shows scorecard, next prayer, rescue plan, sleep protocol, streaks, trend summary, quick logs, due work, focus items, and inbox-ready items on the live stack.
- [x] WebUI `Today` includes Commitment Radar and AI Focus Coach.
- [x] WebUI quick-log buttons update same-day scorecard state without reload in local automated coverage.
- [x] WebUI quick-log buttons update same-day scorecard state without reload on the live stack.
- [ ] SSE updates reach the WebUI after token exchange without manual refresh.
- [ ] Jobs can be created, edited, paused, resumed, deleted, and inspected for run logs.
- [ ] Discord natural-language job creation works with follow-up prompts when fields are missing.
- [ ] Discord one-time jobs work with `tomorrow at 9am`, `on YYYY-MM-DD at HH:MM`, and `in 10 min`.
- [ ] Discord job targeting works with both `<#channel_id>` and manual `#channel-slug` references.
- [ ] Discord natural-language agent creation queues a pending approval correctly.
- [ ] Prayer dashboard loads and prayer check-ins can be edited from WebUI.
- [ ] Quran logging and progress tracking work.
- [ ] Provider telemetry and experiment history load in WebUI.
- [ ] Free-only provider mode is active unless a deliberate paid-provider test sets `FREE_ONLY_MODE=false`.
- [ ] Voice preview works in WebUI for a speech-enabled agent.
- [ ] Discord voice join, speak, interrupt, and leave flows work if voice is part of the release scope.

## Data Safety

- [ ] Workspace archive entries are created before file mutations.
- [ ] Workspace archive restore works from WebUI or API.
- [ ] Backup completed with `./scripts/backup.sh`.
- [ ] Backup verified with `./scripts/verify_backup.sh`.
- [ ] Restore dry-run tested with `./scripts/restore.sh <tag-or-commit> --dry-run`.

## Quality

- [x] Backend tests pass in the target environment.
- [x] Discord bot tests pass in the target environment.
- [x] WebUI tests pass in the target environment.
- [x] Docker images build successfully.
- [x] Local automated coverage exists for daily accountability API, commitment capture/follow-up, Discord smoke commands, Discord quick logs, WebUI Today board, pending chat state, nav smoke, and Playwright Today quick-log flow.
- [x] Manual Discord smoke test completed.
- [x] Manual WebUI smoke test completed.
- [x] Manual Today accountability smoke test completed in both Discord and WebUI.
- [ ] `./scripts/promote_to_main.sh` completed and redeployed the VPS to `main`.
- [x] Docs reviewed for the current stack and operator workflow.
