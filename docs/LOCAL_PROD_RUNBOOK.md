# LifeOS Local Production Runbook

This runbook is for the current Docker Compose deployment model.

## 1. Preconditions

- Linux or WSL2 host with Docker Compose
- Docker daemon reachable from that host or WSL distro (`docker version` succeeds)
- Repo checked out locally
- `.venv/.env` present
- Backend and WebUI kept on localhost unless you have a reverse proxy in front of them

Required env values before boot:

- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ID`
- `DISCORD_OWNER_IDS`
- `API_SECRET_KEY`
- At least one LLM provider key

Recommended:

- `OPENVIKING_API_KEY`
- `BRAVE_API_KEY`

## 2. Preflight

```bash
cp .env.example .venv/.env
nano .venv/.env
docker version >/dev/null
./scripts/startup_self_check.sh
docker compose config >/dev/null
```

Preflight expectations:

- Docker daemon responds before any Compose action
- `API_SECRET_KEY` has been replaced with a strong random value
- `DISCORD_OWNER_IDS` contains at least one real Discord user ID
- Docker Compose config renders successfully

## 3. Start The Stack

```bash
docker compose up --build -d
docker compose ps
```

Expected services:

- `backend`
- `discord-bot`
- `webui`
- `openviking`
- `tts-worker`

## 4. Verify Runtime Health

Basic health:

```bash
curl http://localhost:8100/api/health
curl http://localhost:8100/api/readiness
```

Protected checks:

```bash
TOKEN='<your API_SECRET_KEY>'
curl -H "X-LifeOS-Token: $TOKEN" http://localhost:8100/api/agents/
curl -H "X-LifeOS-Token: $TOKEN" http://localhost:8100/api/tts/health
curl -H "X-LifeOS-Token: $TOKEN" http://localhost:8100/api/settings/
```

Healthy deployment signs:

- `/api/health` reports backend status and OpenViking health
- `/api/readiness` reports `ready`
- WebUI opens at [http://localhost:3100](http://localhost:3100)
- Discord bot answers `!status`

## 5. First-Time Setup After Boot

### WebUI

1. Open [http://localhost:3100](http://localhost:3100).
2. Paste `API_SECRET_KEY` into the token banner.
3. In `Profile`, set timezone, city, country, prayer method, work shift, quiet hours, and nudge mode.
4. In `Settings`, set `data_start_date` and confirm autonomy and approval rules.
5. In `Providers`, confirm your intended providers show as configured.
6. In `Today`, confirm scorecard, next prayer, rescue plan, and quick-log controls render for local day.
7. In `Today`, confirm sleep protocol, streaks, and 7-day trend summary also render.

### Discord

Run a short smoke test:

```text
!status
!agents
!today
!prayertoday
!pending
!sleep 7.5 baseline check
!water 1 startup smoke
!commit send invoice tomorrow at 9am
!focus
```

`!today` should now return a fuller embed, not only title/time. Empty sections should show `none`.
`!commit` should either create a tracked commitment with a reminder, or clearly show an inbox id and a copyable `!commitfollow <inbox_id> <answer>` command.

Optional workflow smoke tests:

```text
!schedule remind me to stretch in #fitness-log using health-fitness
!reply every weekday at 7:30
!joinvoice sandbox
!speak sandbox testing voice output
!leavevoice
```

## 6. Daily Operations

### Today Board

Use WebUI `Today` as primary accountability surface.

Check:

- scorecard metrics for sleep, meals, water, training, shutdown, protein, family, and priorities
- next-prayer window
- rescue-plan headline and actions
- sleep protocol targets and latest logged sleep timing
- streak summary across anchor metrics
- 7-day completion trend summary
- commitment radar, AI focus coach, due today, overdue, top focus, and inbox-ready panels

Quick actions:

- WebUI buttons for `Meal +1`, `Protein Meal`, `Water +1`, `Train`, `Rest Day`, `Family Action`, `Priority Done`, and `Shutdown`
- sleep form in `Today`
- Discord quick logs: `!sleep`, `!meal`, `!train`, `!water`, `!shutdown`
- Discord `!today` for compact remote status when you are away from the browser

### Commitment Loop

Use Discord as the fastest capture surface for promises and follow-through:

- `!commit <message>` starts a fresh AI commitment-capture session.
- `!commitfollow <inbox_id> <answer>` continues a clarifying commitment using the inbox id shown by the bot.
- `!commitfollow session #<session_id> <answer>` is available when you explicitly want session-id mode.
- `!snooze <life_item_id> <time phrase>` moves a commitment and resyncs its linked reminder.
- `!focus` shows deterministic ranking.
- `!focuscoach` asks the commitment coach AI to choose from the backend-provided shortlist.
- `!commitreview` runs an on-demand weekly commitment review.

Deadline examples:

- `tomorrow at 9am`
- `today at 18:00`
- `in 2 hours`
- `today eod`
- `tomorrow end of day`

Expected behavior:

- clear commitments auto-promote to Life items
- vague commitments remain in Inbox with follow-up questions
- one linked reminder job is created per tracked commitment
- repeated follow-up on the same inbox/session does not create duplicate Life items
- `done` and `missed` disable the linked reminder
- `snooze` and `reopen` resync the linked reminder

Important:

- daily scorecards are keyed by local date from `Profile` timezone
- if date/time feels wrong, check `Profile` before debugging app logic

### Mission Control

Check WebUI `Mission Control` for:

- system health
- readiness
- pending approvals
- job status and recent runs
- prayer summary
- recent agent activity

Realtime updates come through SSE and should keep the dashboard current without manual refresh once the token is set.

### Approvals

Use either:

- Discord: `!pending`, `!approve`, `!reject`
- WebUI: `Approvals`

Anything involving agent creation, job proposals, or risky mutations should be reviewed there.

### Jobs

Use WebUI `Jobs` or Discord automation commands to manage jobs.

Operator guidance:

- Every job should have a meaningful `description`.
- Prefer explicit target channels, ideally native Discord mentions like `<#123456789012345678>`.
- If you type a plain channel reference manually, use the actual Discord slug form like `#fitness-log`. Channel names do not contain spaces.
- Use a real timezone per job.
- Remember the backend accepts either:
  - recurring cron: `30 7 mon-fri` or `30 7 * * mon-fri`
  - one-time run_at values stored in UTC and rendered in the job timezone

Discord examples:

- `!schedule every weekday at 7:30 remind me to stretch in #fitness-log using health-fitness`
- `!schedule tomorrow at 9am remind me to review /workspace/docs/spec.md using sandbox silently`
- `!schedule in 10 min remind me to post the recap notify in <#123456789012345678> using sandbox`

### Agents And Sessions

Use WebUI `Agents` for:

- prompt and provider changes
- fallback provider/model changes
- cadence changes
- speech and TTS settings
- workspace path scoping
- workspace sync and archive restore
- chat session review

Use Discord sessions when you want long-running context without mixing topics:

- `!sessions <agent>`
- `!newsession <agent>`
- `!usesession <agent> <id>`
- `!history <agent>`

### Prayer And Quran

Daily checks:

- `!prayertoday`
- `!prayer`
- `!quranprogress`
- WebUI `Today`
- one or more quick logs for anchors you already completed

Weekly review:

- WebUI `Prayer`
- `GET /api/prayer/weekly-summary`

### Provider Health And Experiments

Use WebUI `Experiments` to inspect:

- provider latency
- token averages
- success/failure counts
- circuit-breaker state
- shadow-router win history

## 7. Backup And Restore

Create a repo-level backup:

```bash
./scripts/backup.sh
./scripts/verify_backup.sh
```

Dry-run a restore first:

```bash
./scripts/restore.sh <tag-or-commit> --dry-run
```

Important restore warning:

- `scripts/restore.sh` stops the stack and performs a `git checkout`.
- Do not run it casually on a dirty worktree.
- If you need a safe recovery point first, run `./scripts/backup.sh`.

## 8. Troubleshooting

| Problem | What to check |
| --- | --- |
| `/api/health` is `degraded` | `docker compose logs -f openviking backend` |
| `/api/readiness` is not `ready` | database mount, OpenViking health, startup logs |
| WebUI keeps asking for token | verify `API_SECRET_KEY`, re-enter token, inspect browser console |
| Discord bot is online but commands fail | `docker compose logs -f discord-bot`, confirm `BACKEND_URL` and token |
| Jobs exist but do not fire | `docker compose logs -f backend`, inspect WebUI `Jobs` and `/api/jobs/<id>/runs` |
| Provider failures or slow responses | WebUI `Experiments`, provider key config, circuit-open state |
| Voice playback fails | `docker compose logs -f tts-worker discord-bot`, confirm `ffmpeg` and Opus availability |
| Workspace answers feel stale | resync from WebUI `Agents` or `POST /api/workspace/sync` |
| Prayer reminders do not post | confirm `DISCORD_OWNER_IDS`, profile timezone/location, reminder channels, bot permissions |
| Today board shows wrong day or stale rescue state | confirm `Profile` timezone, reload `Today`, inspect `/api/life/today`, then backend logs |

Useful log commands:

```bash
docker compose logs -f backend
docker compose logs -f discord-bot
docker compose logs -f webui
docker compose logs -f openviking
docker compose logs -f tts-worker
```

## 9. Operational Habits That Pay Off

- Keep `Profile` and `Settings` accurate before judging the quality of planner or prayer outputs.
- Use approval queues for new automations until the wording is stable.
- Keep workspace-enabled agents scoped to the smallest useful path set.
- Review job run logs before assuming an automation is broken.
- Treat `Experiments` as the source of truth for provider health, not guesswork.
