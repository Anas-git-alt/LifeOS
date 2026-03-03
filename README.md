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

### 3) Approval-gated NL Creation from Discord
- New Discord commands:
  - `!schedule <natural language>`
  - `!spawnagent <natural language>`
  - `!reply <answer>` for follow-up prompts
  - `!jobs [agent]`
- Missing fields trigger follow-up questions before proposal submission.
- Final creation is queued as `PendingAction` and requires approval (`!approve`).

---

## 📋 Setup Guide A: Windows → WSL2 → Running System

### Prerequisites

#### 1. Enable WSL2

Open **PowerShell as Administrator**:

```powershell
# Install WSL2 with Ubuntu 24.04 LTS (Noble Numbat — latest LTS, supported until 2029)
wsl --install -d Ubuntu-24.04

# Restart your computer when prompted
# On first launch, create a Unix username + password
```

> **Why Ubuntu 24.04?** It's the latest LTS (released April 2024). 5 years of free security updates. Widest Docker/tooling compatibility.

#### 2. Install Docker (inside WSL2)

**Option A — Docker Engine (recommended for WSL2):**

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

**Option B — Docker Desktop (Windows):**
- Download from https://docker.com/products/docker-desktop
- During setup, enable "Use WSL 2 based engine"
- In Settings → Resources → WSL Integration → Enable for Ubuntu-24.04

#### 3. Install Git

```bash
sudo apt install -y git
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

#### 4. Clone Repo + Secrets

```bash
cd ~
git clone <your-repo-url> LifeOS
cd LifeOS

# Create secrets directory (stays inside .venv, excluded by .gitignore)
mkdir -p .venv
cp .env.example .venv/.env

# Edit secrets — add your Discord token + at least one LLM API key
nano .venv/.env
```

**How secrets work:** The backend loads `.venv/.env` via `python-dotenv`. Docker Compose mounts it via `env_file: .venv/.env`. The `.gitignore` excludes `.venv/` entirely, so secrets are **never committed**.

#### 5. Get API Keys (free)

| Provider | Free Tier | Get Key |
|---|---|---|
| **OpenRouter** | 50 req/day, dozens of free models | https://openrouter.ai/keys |
| **NVIDIA NIM** | 1000 free credits | https://build.nvidia.com |
| **Google Gemini** | Optional (free tier available) | https://aistudio.google.com/apikey |
| **OpenAI** | Optional (paid) | https://platform.openai.com/api-keys |

#### 6. Create Discord Bot

1. Go to https://discord.com/developers/applications
2. Click **"New Application"** → name it "LifeOS"
3. Go to **"Bot"** tab:
   - Click "Reset Token" → copy the token → paste in `.venv/.env` as `DISCORD_BOT_TOKEN`
   - Enable **all** Privileged Gateway Intents:
     - ✅ Presence Intent
     - ✅ Server Members Intent
     - ✅ Message Content Intent
4. Go to **"OAuth2" → "URL Generator"**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Read Message History`, `Add Reactions`, `Embed Links`, `Manage Messages`
   - Copy the URL → open it → select your server → Authorize
5. Copy your server ID → paste in `.venv/.env` as `DISCORD_GUILD_ID`
   - (Right-click server name → Copy Server ID; enable Developer Mode in Discord settings first)

#### 7. Create Discord Channels

Create these categories and channels in your Discord server:

```
📁 LIFEOS
  #dashboard, #approval-queue, #audit-log
📁 DEEN
  #prayer-tracker, #daily-adhkar
📁 FAMILY
  #wife-commitments, #family-calendar
📁 WORK
  #ai-content, #analytics
📁 HEALTH
  #fitness-log, #habits
📁 PLANNING
  #daily-plan, #weekly-review
```

#### 8. Launch

```bash
cd ~/LifeOS
docker compose up --build -d

# Watch logs
docker compose logs -f

# Check status
docker compose ps
```

#### 9. Smoke Test

```bash
# Backend health
curl http://localhost:8100/api/health
# Expected: {"status":"healthy","service":"lifeos-backend","version":"0.1.0"}

# List agents
curl http://localhost:8100/api/agents/
# Expected: 7 default agents (including `sandbox`)

# WebUI
# Open http://localhost:3100 in your browser

# Discord
# In any channel, type: !status
# Expected: Bot responds with system health embed
```

### Troubleshooting Checklist

| Problem | Fix |
|---|---|
| `docker compose` not found | Run `sudo apt install docker-compose-plugin` |
| Permission denied on Docker | Run `sudo usermod -aG docker $USER && newgrp docker` |
| Bot not responding in Discord | Check `DISCORD_BOT_TOKEN` in `.venv/.env`; verify Message Content Intent is ON |
| Backend crash on startup | Run `docker compose logs backend` — usually a missing env var |
| WebUI blank page | Check `docker compose logs webui`; ensure backend is healthy first |
| Port 8100 already in use | `sudo lsof -i :8100` and kill the process, or change `BACKEND_PUBLIC_PORT` |
| Can't connect to LLM | Verify API key in `.venv/.env`; check `!providers` in Discord |
| SQLite locked error | Only one backend instance should run; `docker compose down` first |
| WSL2 can't access internet | Run `wsl --shutdown` in PowerShell, then reopen Ubuntu |
| Docker Desktop WSL integration | In Docker Desktop → Settings → Resources → WSL Integration → Enable Ubuntu |

---

## 📋 Setup Guide B: VPS (Fresh Ubuntu 24.04 LTS)

### 1. Initial Server Setup

```bash
# SSH in as root
ssh root@your-server-ip

# Create non-root user
adduser lifeos
usermod -aG sudo lifeos

# SSH hardening
nano /etc/ssh/sshd_config
# Set: PermitRootLogin no
# Set: PasswordAuthentication no  (after adding SSH key)
systemctl restart sshd

# Switch to new user
su - lifeos
```

### 2. Install Docker

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### 3. Deploy

```bash
git clone <your-repo-url> ~/LifeOS && cd ~/LifeOS
mkdir -p .venv && cp .env.example .venv/.env
nano .venv/.env  # Add secrets
docker compose up --build -d
```

### 4. Firewall

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 3100/tcp   # WebUI (or restrict to your IP)
# Do NOT expose 8100 directly to public internet unless required
sudo ufw enable
```

### 5. Optional: HTTPS with Caddy

If you have a domain:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# Add to /etc/caddy/Caddyfile
# yourdomain.com {
#     reverse_proxy localhost:3100
# }

sudo systemctl restart caddy
```

### 6. Backups & Persistence

```bash
# Docker volumes are in standard locations
# SQLite DB is in ./storage/lifeos.db (mounted volume)

# Automated backup via cron
crontab -e
# Add: 0 2 * * * cd /home/lifeos/LifeOS && ./scripts/backup.sh >> /tmp/backup.log 2>&1

# Restore from backup
./scripts/restore.sh backup-2026-02-27
```

### 7. Optional: fail2ban

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
```

---

## 🤖 Default Agents

| Agent | Purpose | Discord Channel | Schedule |
|---|---|---|---|
| **prayer-deen** | Prayer reminders, adhkar, Quran tracker | #prayer-tracker | ~prayer times |
| **marriage-family** | Commitment tracker, date ideas, gentle reminders | #wife-commitments | Daily 9am |
| **work-ai-influencer** | Shift reminders, AI content ideas, analytics | #ai-content | Daily 1pm |
| **health-fitness** | Workout plans, meals, consistency tracking | #fitness-log | Daily 8am |
| **daily-planner** | Morning briefing, ADHD time blocks, conflicts | #daily-plan | Daily 7am |
| **weekly-review** | Sunday recap, wins/misses, next week goals | #weekly-review | Sunday 10am |
| **sandbox** | General testing agent for prompts, tools, and experiments | — | Manual |

### Example Discord Commands

```
!daily                    → Get today's schedule
!sandbox Plan my week around work + prayer
!ask prayer-deen Did I pray Dhuhr?
!ask health-fitness I did 30 min yoga today
!wife promised to get flowers tomorrow
!workout upper body push, 40 mins
!sessions sandbox         → List sandbox sessions
!newsession sandbox Focus week plan
!usesession sandbox 12
!history sandbox          → Show active session history
!clearsession sandbox     → Reset active session context
!prayer                   → Log a prayer
!prayertoday              → Show today's real prayer windows
!prayerlog 2026-03-01 Fajr late overslept
!quran 2 4               → Log Quran progress (juz + pages)
!tahajjud done           → Log tahajjud
!adhkar morning done     → Log morning adhkar
!weekly                   → Trigger weekly review
!pending                  → View approval queue
!approve 1                → Approve action #1
!reject 2 Not needed      → Reject action #2
!status                   → System health
!providers                → LLM provider status
!agents                   → List all agents
```

### Chat Sessions (WebUI + Discord)

- **WebUI**: open `Agents` → select an agent → `Chat` tab.
- Create or switch sessions from the left panel.
- Use **Clear context** to wipe only that session history.
- Session titles auto-generate from the first 1-3 prompts.
- **Discord** keeps an active session per `(guild, channel, user, agent)`:
  - `!sessions <agent>`
  - `!newsession <agent> [title]`
  - `!usesession <agent> <session_id>`
  - `!renamesession <agent> <session_id> <title>`
  - `!clearsession <agent> [session_id]`
  - `!history <agent> [session_id]`
  - `!ask` and `!sandbox` automatically use the active session.

### Deen Accountability (Prayer + Habits)

- Prayer schedule + windows: `GET /api/prayer/schedule/today`
- Prayer check-ins:
  - Real-time: `POST /api/prayer/checkin`
  - Retroactive: `POST /api/prayer/checkin/retroactive`
- Deen habits:
  - Quran: `POST /api/prayer/habits/quran`
  - Tahajjud: `POST /api/prayer/habits/tahajjud`
  - Adhkar: `POST /api/prayer/habits/adhkar`
- Weekly metrics: `GET /api/prayer/weekly-summary` (on-time rate, completion, retroactive logs, Quran, tahajjud, adhkar)
- Discord prayer reminders support reaction logging:
  - `✅` on-time, `🕒` late, `❌` missed

### Sample Daily Report

```
🌅 Good Morning! | Tuesday, Feb 27

📋 Today's Focus (3 Items):
  1. 🏋️ Morning workout — upper body (30 min)
  2. 🤖 Draft AI workflow post for LinkedIn
  3. 💕 Pick up flowers for wife

⏰ Time Blocks:
  07:00 – 07:30  🕌 Fajr + morning adhkar
  07:30 – 08:00  🏋️ Workout
  08:00 – 13:00  🏠 Personal time
  13:30 – 14:00  🍽️ Lunch + prep for shift
  14:00 – 00:00  💼 Work shift
  (Prayers embedded: Dhuhr 12:30, Asr 15:45, Maghrib 18:15, Isha 19:45)

❤️ Family: Remember the flowers!
```

### Sample Weekly Report

```
📊 Weekly Review — Feb 23–27

✅ Wins:
  • Prayed all 5 prayers on time: 4/5 days
  • Prayer on-time accuracy: 29/35 (82.86%)
  • Retroactive prayer logs: 2
  • Quran progress: max juz 8, pages read this week 46
  • Tahajjud: 4/4 target
  • Adhkar consistency: morning 6/7, evening 5/7
  • Published 2 AI content posts
  • Completed 3 workouts

⚠️ Missed:
  • Forgot date night on Thursday
  • Skipped Friday workout

📈 Streaks: Prayer 4 days | Workout 3 days | Content 5 days

🎯 Next Week Focus:
  1. Schedule date night for Wednesday
  2. Try morning workouts (before shift)
  3. Draft video script for AI agents tutorial
```

---

## 🔧 Ops & Maintenance

### Backups

- **Automated daily**: GitHub Actions runs at 2 AM UTC (see `.github/workflows/backup.yml`)
- **Manual**: `./scripts/backup.sh` — commits + tags + pushes
- **Cadence**: Daily pushes recommended; git tags make rollback easy

### Rollback

```bash
# List available backups
git tag -l "backup-*" | sort -r | head -10

# Restore to specific backup
./scripts/restore.sh backup-2026-02-27

# Go back to latest
git checkout main && docker compose up --build -d
```

### Monitoring

- **Health endpoint**: `GET /api/health` — used by Docker healthcheck
- **Discord alerts**: Bot sends 🚨 alert if backend is unreachable (checked every 6 hours)
- **Manual health check**: `./scripts/health_check.sh`
- **Logs**: `docker compose logs -f [service]`

### Safe Upgrade Process

```bash
# 1. Tag current state
git tag "pre-upgrade-$(date +%Y%m%d)"

# 2. Pull changes
git pull origin main

# 3. Rebuild
docker compose up --build -d

# 4. Verify
curl http://localhost:8100/api/health
# Type !status in Discord

# 5. If broken, rollback
./scripts/restore.sh pre-upgrade-20260227
```

### Scaling Path

| Stage | Change | Effort |
|---|---|---|
| **Current** | 1 machine, SQLite, Docker Compose | ✅ Done |
| **More users** | SQLite → PostgreSQL (change `DATABASE_URL`) | 1 hour |
| **Higher throughput** | Add Redis for queue + caching | 2 hours |
| **Multiple services** | Split backend into API + worker | 1 day |
| **Multi-machine** | Docker Swarm or k8s (outline below) | 1 week |

**Stateless services** (scale horizontally): webui, discord-bot
**Stateful services** (need persistence): backend (DB), storage volume

**Optional k8s outline** (don't overbuild now):
- Convert `docker-compose.yml` → Helm chart
- Backend → Deployment + Service
- Database → StatefulSet with PVC
- WebUI → Deployment + Ingress
- Secrets → Kubernetes Secrets

---

## 🧬 SkillOps — Self-Improving Skills

Skills are versioned modules in `/skills/<name>/` that extend agent capabilities.

### Structure

```
skills/<skill_name>/
├── manifest.yaml    # Name, version, description, triggers, I/O
├── skill.py          # Implementation
└── tests/
    └── test_<name>.py
```

### Workflow

1. System (or user) identifies improvement opportunity
2. Creates git branch `skill/<name>`
3. Adds skill module with manifest + code + tests
4. Opens PR on GitHub
5. **GitHub Actions automatically**: validates manifest, runs tests
6. **User must manually**: review, approve, and merge PR
7. After merge: `docker compose restart backend`

### Safety Policy

| Action | Automated? |
|---|---|
| Propose new skill (open PR) | ✅ Yes |
| Run tests on skill PR | ✅ Yes |
| Update dependencies (Dependabot) | ✅ Yes (PR only) |
| Merge PR | ❌ Manual only |
| Deploy changes | ❌ Manual only |
| Delete skills | ❌ Manual only |
| Modify system prompts | ❌ Manual only |

---

## 🏗️ Architecture

```
User ──► Discord ──► Discord Bot ──► Backend API ──► Agent Orchestrator
                                          ↕                    ↕
User ──► WebUI  ──────────────────► Backend API      Provider Router
                                          ↕           (OpenRouter/NVIDIA/
                                    Approval Queue     Google/OpenAI)
                                          ↕
                                   SQLite Database
                                   (agents, chat_sessions,
                                    memory, prayer windows,
                                    deen habits, approvals, audit)
```

### Approval Flow

1. Agent drafts action and is risk-classified (`low` / `medium` / `high`)
2. Bot posts to `#approval-queue` with ✅/❌ reactions
3. Medium/high-risk actions become `PENDING`; low-risk responses can return immediately
4. User approves via Discord reaction OR WebUI button OR `!approve <id>`
5. If approved → action executes; if rejected → logged and discarded
6. All decisions logged in audit_log table

---

## ⬆️ Optional Next Upgrades

- [ ] **SearXNG** self-hosted search (replace DuckDuckGo for unlimited queries)
- [ ] **Google Calendar** integration (replace calendar stub)
- [ ] **Email** integration (SMTP/Gmail API)
- [ ] **Telegram** bot adapter (reuse same backend API)
- [ ] **Voice memos** transcription (Whisper)
- [ ] **RAG** memory (ChromaDB/Qdrant for vector search)
- [ ] **Ollama** local LLM support (add as 5th provider)
- [ ] **Mobile PWA** for webUI
- [ ] **Multi-user** auth (add JWT middleware)

---

## 🔒 Security Notes

- Secrets stored in `.venv/.env` — excluded by `.gitignore`
- Approvals are risk-based (`medium/high` require approval, `low` can auto-complete)
- Docker containers run as non-root where possible
- Default localhost bindings are `127.0.0.1:3100` (webui) and `127.0.0.1:8100` (backend)
- On VPS: expose WebUI with reverse proxy and keep backend internal where possible
- API keys have minimal scopes — rotate quarterly
- **Never commit `.venv/.env`** — the backup script checks for this

---

## 📄 License

MIT — Free to use, modify, and distribute.

---

*Bismillah — Built with the intention of helping organize life for the better.* 🤲
