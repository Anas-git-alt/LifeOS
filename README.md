# LifeOS

LifeOS is a self-hosted AI agent system for personal operations. The daily loop is intentionally simple: capture once in Discord or Today, let LifeOS auto-sort it, then review Today for focus, habits, reminders, prayer context, and anything that needs an answer. Behind that loop are FastAPI, the Discord bot, token-gated WebUI, OpenViking runtime memory and workspace search, optional Obsidian shared memory, scheduled jobs, approval gates, prayer and Quran tracking, daily scorecards, commitment follow-up, and optional voice/TTS playback.

The recommended way to run it today is Docker Compose on Linux or WSL2.

## Current Stack

| Service | Purpose | Port |
| --- | --- | --- |
| `backend` | FastAPI API, orchestration, approvals, jobs, prayer and life data, realtime events | `127.0.0.1:8100 -> 8000` |
| `discord-bot` | Primary user interface in Discord | host network |
| `webui` | React control plane and dashboards | `127.0.0.1:3100 -> 80` |
| `openviking` | Memory backend, workspace indexing, repo/external resource search | internal only |
| `tts-worker` | Local text-to-speech synthesis for voice workflows | internal only |

Important runtime notes:

- Most API routes require `X-LifeOS-Token`, which should match `API_SECRET_KEY`.
- The WebUI asks for that token once and stores it in browser local storage.
- The backend currently requires OpenViking to be enabled and reachable at startup.
- If `OBSIDIAN_VAULT_ROOT` is configured, LifeOS treats that vault as the durable shared wiki and indexes it into OpenViking for targeted retrieval.
- Backend and WebUI are intentionally bound to `127.0.0.1` by default. Put them behind a reverse proxy before exposing them remotely.

## Quick Start

1. Clone the repo and create the env file.

```bash
git clone <your-repo-url> ~/LifeOS
cd ~/LifeOS
mkdir -p .venv
cp .env.example .venv/.env
```

Optional, if you want zero user runtime data inside repo:

```bash
cp compose.env.example .env
# edit .env with absolute host paths outside repo
```

2. Edit `.venv/.env` and set at least:

- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ID`
- `DISCORD_OWNER_IDS`
- `API_SECRET_KEY`
- At least one free-friendly provider key: `OPENROUTER_API_KEY` with `OPENROUTER_DEFAULT_MODEL=openrouter/free`, or `NVIDIA_API_KEY` for NIM free-tier endpoints. `FREE_ONLY_MODE=true` blocks paid OpenAI/Google paths by default.

Recommended:

- `OPENVIKING_API_KEY` if you do not want OpenViking to reuse `API_SECRET_KEY`
- `BRAVE_API_KEY` for Brave-backed web search instead of DuckDuckGo fallback
- `OBSIDIAN_VAULT_ROOT=/obsidian-vault` if you want durable cross-agent shared memory in an external Obsidian vault mounted into Docker

3. Run the startup check and start the stack.

In WSL, make sure Docker Desktop integration or a local Docker daemon is already running first:

```bash
docker version
```

```bash
./scripts/startup_self_check.sh
docker compose up --build -d
```

4. Verify health.

```bash
docker compose ps
curl http://localhost:8100/api/health
curl http://localhost:8100/api/readiness
```

5. Open the control plane at [http://localhost:3100](http://localhost:3100) and paste `API_SECRET_KEY` into the token banner.

Runtime-data note:

- `.venv/.env` is for app secrets and service env vars.
- repo-root `.env` is optional and only for Docker host mount overrides such as runtime data paths.
- In Docker/Compose, set `OBSIDIAN_VAULT_ROOT=/obsidian-vault` in `.venv/.env` and set `LIFEOS_OBSIDIAN_VAULT_DIR=/absolute/host/path` in repo-root `.env`.
- See [docs/RUNTIME_DATA.md](docs/RUNTIME_DATA.md) if you want a clean repo with runtime data stored elsewhere.

## First-Use Checklist

After the stack is up, do this once before relying on automations:

1. In WebUI `Profile`, set your timezone, city, country, prayer method, work shift, quiet hours, and nudge mode.
2. In WebUI `Settings`, confirm `data_start_date`, default timezone, autonomy, and mutation approval rules.
3. In WebUI `Providers`, confirm the provider keys you expect are actually configured.
4. In Discord, run `!status`, `!agents`, `!today`, and `!prayertoday`.
5. In WebUI `Agents`, inspect the seeded agents and adjust prompts, cadence, fallback models, voice settings, or workspace access as needed.
6. In WebUI `Today`, confirm scorecard, next prayer, rescue plan, and quick-log buttons render for your local day.
7. In Discord, try quick accountability logs such as `!sleep 7.5 bed 23:30 wake 07:10 solid night`, `!family called parents`, or `!priority shipped invoice`.
8. In Discord, try one capture loop such as `!capture need invoice sent today and sleep routine fixed`, then check `!today` or WebUI `Today`.

Seeded by default:

- `intake-inbox`
- `commitment-capture`
- `commitment-coach`
- `prayer-deen`
- `marriage-family`
- `work-ai-influencer`
- `health-fitness`
- `daily-planner`
- `weekly-review`
- `sandbox`

Optional advisory agents are seeded only when `AGENCY_AGENTS_ENABLED=true`:

- `code-reviewer`
- `qa-engineer`
- `editorial-writer`

## How To Use It Effectively

- Start with one loop: capture raw input, review Today, answer only what LifeOS asks.
- Use Discord for capture and lightweight execution. It is the fastest place to capture, ask agents, approve actions, log prayer and Quran habits, and trigger jobs.
- Use WebUI `Today` for daily review. It shows scorecard, rescue plan, next prayer, commitment radar, AI focus coach, due commitments, focus items, capture questions, and memory review.
- Use `!capture` for messy raw life input, promises, meeting notes, durable facts, reminders, goals, habits, and ideas. LifeOS auto-sorts the input into tracked work, clarification questions, or memory review.
- Use `!commit` and `!meeting` only as power shortcuts. They route through the same unified capture path.
- Normal agent chats are grounded on the LifeOS state packet. If the packet cannot be built, the agent fails closed instead of inventing your status.
- Free-text daily logs are confirmable. If chat text sounds like a completed check-in, LifeOS proposes a log and waits for a check-mark reaction before mutating Today.
- Recipe, budget, and explanation follow-ups should stay as chat, not become logs. For example, `more details for the egg meal` answers the recipe; `meal prepared and eaten` proposes a meal log.
- Current external facts use web search when needed. Weather defaults to your profile city/country; LifeOS planning questions such as `what should I do today?` use the state packet, not web search.
- Use `!focus` for backend-ranked priority and `!focuscoach` when you want AI help choosing the next visible step.
- Keep conversations separated with sessions. Active session memory is scoped per guild, channel, user, and agent, so `!newsession`, `!usesession`, and the WebUI chat tab are worth using intentionally.
- Use the Obsidian vault for durable shared knowledge. Session chat stays transient; memory review proposals live in Today/Wiki review before they are applied to the vault.
- Give jobs a clear `description`. Jobs support recurring cron schedules and one-time run times.
- Prefer approval queues for risky changes. New agents and natural-language job creation are safer when you queue them first and review them in `Approvals`.
- Keep workspace access narrow. If an agent needs repo access, enable workspace support only for the paths it really needs, then use `Sync Workspace` and rely on archives for rollback.
- Watch `Experiments` before changing providers. The project tracks live provider telemetry, circuit-breaker state, and shadow-router results when `SHADOW_ROUTER_ENABLED=true`; it is off by default to protect free quota.
- Treat voice as an explicit feature. Enable speech on the agent, preview its voice in WebUI, then use `!joinvoice`, `!speak`, and `!interrupt` in Discord.
- Use quick logs for anchors instead of waiting for review. `!sleep`, `!meal`, `!train`, `!water`, `!family`, `!priority`, and `!shutdown` update same-day accountability state immediately.

See [docs/AGENTIC_GROUNDING_AND_CAPTURE.md](docs/AGENTIC_GROUNDING_AND_CAPTURE.md) for the current simplify-grounding behavior, regression tests, and next suggested improvements.

Useful example workflows:

- Daily planning: `!daily`, then refine in a dedicated `daily-planner` session.
- Raw life capture: `!capture need invoice sent today, sleep routine is broken, and invoices are high leverage for payment loops`.
- Quick accountability log: `!sleep 7.5 bed 23:30 wake 07:10`, `!meal protein shake`, `!water 2 after walk`, `!train rest sore today`, `!family called parents`, `!priority shipped invoice`, `!shutdown inbox zero`.
- Commitment capture: `!commit create the Canva file deadline is today eod`, then `!focuscoach`.
- Commitment follow-up: `!commitfollow 8 specific action is to create the mockup, deadline is today eod`.
- Commitment review: `!commitreview`; the same review is also posted weekly on Sunday 10:00 in `#weekly-review`.
- New reminder job: `!schedule every weekday at 7:30 remind me to stretch in #fitness-log using health-fitness`
- One-time background job: `!schedule tomorrow at 9am remind me to review /workspace/docs/spec.md using sandbox silently`
- One-time Discord post: `!schedule in 10 min remind me to post the recap notify in <#123456789012345678> using sandbox`
- New agent proposal: `!spawnagent create agent named focus-coach to keep me consistent in #planning every day at 8:00 approval auto`
- Workspace-enabled agent tuning: WebUI `Agents` -> select agent -> update workspace paths -> `Sync Workspace`

Job authoring tips:

- Prefer native Discord channel mentions like `<#123456789012345678>` when scheduling from Discord.
- If you type a plain channel reference manually, use the real Discord slug form like `#fitness-log`. Channel names do not contain spaces.
- One-time jobs are stored in UTC internally and rendered back in the job timezone.

## WebUI Surfaces

| Page | What it is for |
| --- | --- |
| `Mission Control` | Health, readiness, approvals, jobs, prayer summary, and recent agent activity with realtime updates |
| `Today` | Daily accountability board with capture, scorecard, next prayer, rescue plan, quick logs, commitment radar, AI focus coach, due work, focus items, capture questions, and memory review |
| `Inbox` | Advanced/internal capture review for clarifying, ready, and processed entries |
| `Wiki` | Advanced/internal memory review for context events and Obsidian proposals |
| `Prayer` | Weekly prayer dashboard with editable check-ins |
| `Quran` | Page-based reading log and bookmark/progress |
| `Life Items` | Tasks, goals, and habits across deen, family, work, health, and planning |
| `Agents` | Prompt, provider, voice, workspace, and session management |
| `Spawn Agent` | Guided agent creation with optional approval queue |
| `Jobs` | Create, edit, pause, resume, delete, and inspect run logs |
| `Approvals` | Pending decision queue |
| `Providers` | Provider availability and capability status |
| `Experiments` | Provider telemetry and shadow-routing results |
| `Profile` | Timezone, shift, quiet hours, and prayer settings |
| `Settings` | Data start date, autonomy, and mutation approval policy |

## Local Development

Docker Compose is the easiest way to get the full system, especially because OpenViking and the TTS worker are already wired up there. If you need component-level dev loops:

### Backend

```bash
python -m venv .python-venv
source .python-venv/bin/activate
cd backend
pip install -r requirements.txt
set -a
source ../.venv/.env
set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Discord Bot

```bash
source .python-venv/bin/activate
cd discord-bot
pip install -r requirements.txt
set -a
source ../.venv/.env
set +a
BACKEND_URL=http://localhost:8000 python -m bot.main
```

### WebUI

```bash
cd webui
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:3000` and proxies `/api` to `http://localhost:8000`.

### TTS Worker

```bash
source .python-venv/bin/activate
cd tts-worker
pip install -r requirements.txt
set -a
source ../.venv/.env
set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```

OpenViking is easiest to run through Compose because the repo already ships the config wrapper used in production.

## Shared Memory

If `OBSIDIAN_VAULT_ROOT` is set, LifeOS bootstraps a managed vault layout and uses it as the durable shared-memory layer:

- `shared/global`
- `shared/domains/{work,health,deen,family,planning}`
- `private/agents/{agent_name}`
- `private/user`
- `inbox/proposals`
- `system/indexes`

OpenViking remains the runtime search/index layer. Retrieval now prefers vault router notes and narrow domain hubs before semantic fallback.

New API surfaces:

- `POST /api/memory/promote`
- `POST /api/memory/proposals/{id}/apply`
- `GET /api/memory/shared/search`
- `POST /api/vault/sync`
- `GET /api/vault/conflicts`

## Tests And Ops Commands

```bash
cd backend && ../.python-venv/bin/python -m pytest -q
cd discord-bot && ../.python-venv/bin/python -m pytest -q
cd webui && npm run test:run
cd webui && npm run test:e2e
./scripts/startup_self_check.sh
./scripts/backup.sh
./scripts/verify_backup.sh
./scripts/restore.sh <tag-or-commit> --dry-run
```

Important:

- The Python test commands above use the repo venv directly. If `.python-venv` is already activated, `python -m pytest -q` is enough.
- `scripts/restore.sh` shuts the stack down, checks out a git target, and starts services again. Treat it as a controlled recovery action and avoid running it on a dirty worktree.
- `scripts/backup.sh` commits and tags the current repo state, so make sure you actually want a repo-level backup before running it.

## Repository Map

- `backend/`: FastAPI app, scheduler, approvals, jobs, prayer/life logic, OpenViking integration
- `discord-bot/`: Discord command handlers, approval reactions, prayer reminders, NL automation flows, voice commands
- `webui/`: React/Vite control plane
- `tts-worker/`: Local TTS service
- `openviking/`: OpenViking bootstrap and config rendering helpers
- `skills/`: Skills mounted into the backend
- `storage/`: SQLite, OpenViking data, workspace archives, and runtime state
- `scripts/`: startup, backup, restore, verification, and health check helpers

## Documentation

- [README.md](README.md): overview, startup, and usage
- [codebase.md](codebase.md): technical architecture and data flow
- [TEST_REPORT.md](TEST_REPORT.md): historical WebUI bug report with link to current revalidation
- [docs/VERIFICATION_2026-04-18.md](docs/VERIFICATION_2026-04-18.md): latest local verification snapshot for daily accountability work
- [docs/VERIFICATION_2026-04-14.md](docs/VERIFICATION_2026-04-14.md): latest live VPS verification snapshot
- [docs/DISCORD_COMMANDS.md](docs/DISCORD_COMMANDS.md): bot command reference
- [docs/DEV_VPS_WORKFLOW.md](docs/DEV_VPS_WORKFLOW.md): local branch to VPS workflow
- [docs/LOCAL_PROD_RUNBOOK.md](docs/LOCAL_PROD_RUNBOOK.md): operator runbook
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md): release and smoke-test checklist
- [docs/RUNTIME_DATA.md](docs/RUNTIME_DATA.md): runtime path and storage layout guidance
- [docs/TEST_AND_CLEANUP_REPORT_2026-04-13.md](docs/TEST_AND_CLEANUP_REPORT_2026-04-13.md): historical cleanup report
- [docs/adr/001-provider-router-circuit-breaker.md](docs/adr/001-provider-router-circuit-breaker.md): provider routing decision record
