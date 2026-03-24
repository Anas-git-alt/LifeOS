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