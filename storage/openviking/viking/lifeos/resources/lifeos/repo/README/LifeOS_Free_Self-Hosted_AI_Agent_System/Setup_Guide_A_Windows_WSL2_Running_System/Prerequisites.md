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
# Expected: {"status":"healthy","service":"lifeos-backend","version":"1-5"}

# List agents
curl http://localhost:8100/api/agents/
# Expected: 7 default agents (including `sandbox`)

# WebUI
# Open http://localhost:3100 in your browser

# Discord
# In any channel, type: !status
# Expected: Bot responds with system health embed
```