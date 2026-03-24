# 🧠 LifeOS — Free Self-Hosted AI Agent System

> Discord-first, session-aware AI agents for life organizing. Runs on WSL2 & VPS via Docker Compose. $0 by default.

Production docs:
- `docs/LOCAL_PROD_RUNBOOK.md`
- `docs/RELEASE_CHECKLIST.md`

---

## ⚡ Quickstart from Zero (TL;DR)

```bash
# 1. Install WSL2 (Windows PowerShell as Admin)
wsl --install -d Ubuntu-24.04

# 2. Inside WSL Ubuntu:
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# 3. Clone + Configure
git clone <your-repo-url> ~/LifeOS && cd ~/LifeOS
mkdir -p .venv && cp .env.example .venv/.env
nano .venv/.env  # Add your Discord token + at least one LLM API key

# 4. Launch
docker compose up --build -d

# 5. Verify
docker compose ps        # All services "Up"
curl http://localhost:8100/api/health  # {"status":"healthy"}
# Open http://localhost:3100 for WebUI
```

---

## 📦 Service Overview

| Service | Purpose | Port | Volumes | Key Env Vars |
|---|---|---|---|---|
| **backend** | FastAPI API + agent orchestrator + scheduler | `8100 -> 8000` | `./storage`, `./skills` | All LLM keys, `DATABASE_URL` |
| **discord-bot** | Discord.py bot with cogs | — | — | `DISCORD_BOT_TOKEN`, `BACKEND_URL` |
| **webui** | React SPA control plane (nginx) | `3100 -> 80` | — | — (proxies to backend) |

---

## 🆕 New Runtime Controls (v0.2+)

### 1) Data Start Date (report filtering, no data deletion)
- API: `GET /api/settings/`, `PUT /api/settings/`
- WebUI: **Global Settings** page
- Behavior:
  - `data_start_date` is **inclusive**
  - analytics/reports/streak-style summaries ignore older entries
  - raw historical rows remain in SQLite (nothing is deleted)
- Default:
  - initialized from first-run local date when possible
  - safe fallback is `2026-03-02` (Africa/Casablanca)

### 2) First-class Jobs Management
- API:
  - `GET /api/jobs/` (global) / `GET /api/jobs/?agent_name=<name>` (per-agent)
  - `POST /api/jobs/`, `PUT /api/jobs/{id}`
  - `POST /api/jobs/{id}/pause`, `POST /api/jobs/{id}/resume`
  - `DELETE /api/jobs/{id}`
  - `GET /api/jobs/{id}/runs` (recent run logs)
- WebUI: **Jobs** page supports create/edit/pause/resume/delete + run visibility.
- Jobs are timezone-aware per row (`timezone` field), defaulting to `Africa/Casablanca`.
- Jobs now include `description` to explain intent and expected output.

### 2.1) Writing Understandable Job Descriptions
Use this short pattern:
- **Intent**: what should happen (`Daily planning reminder`)
- **Audience/Target**: where it goes (`post in #daily-plan`)
- **Outcome**: what the message should help you do (`start top 3 priorities before shift`)

Examples:
- `Daily planning reminder for #daily-plan to set top 3 priorities before 14:00 shift.`
- `Workout prompt in #fitness-log to maintain morning consistency on weekdays.`
- `Weekly review kickoff in #weekly-review to summarize wins, misses, and next-week focus.`

### 3) Approval-gated NL Creation from Discord
- New Discord commands:
  - `!schedule <natural language>`
  - `!spawnagent <natural language>`
  - `!reply <answer>` for follow-up prompts
  - `!jobs [agent]`
- Missing fields trigger follow-up questions before proposal submission.
- Final creation is queued as `PendingAction` and requires approval (`!approve`).

---