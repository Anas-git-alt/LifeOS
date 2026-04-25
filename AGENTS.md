# AGENTS

This file is the short operational map for coding agents working in this repo.

Read this first, then read [docs/SYSTEM_SETUP.md](docs/SYSTEM_SETUP.md) for the full environment layout.

## Workspace Role

Use Codex in the exact worktree that matches the current task.

- `/home/anasbe/LifeOS-feature-<task>`: primary coding workspace for new changes, commits, and PRs
- `/home/anasbe/LifeOS-main-merge`: clean `main` reference worktree; keep this clean and use it for comparison, validation, and fresh branching
- `/home/anasbe/LifeOS-clean`: sandbox/manual-test workspace; this tree may be dirty and should not be treated as the clean source for new feature work
- `/home/anasbe/`: parent folder for organizing related worktrees and backups, not the default Codex working directory

## Current Repo Structure

- `backend/`: FastAPI API, scheduler, providers, jobs, life logic, prayer/Quran logic, workspace tools
- `discord-bot/`: Discord command surface, reminders, approvals, automation helpers, voice
- `webui/`: React/Vite control plane
- `tts-worker/`: local text-to-speech worker
- `openviking/`: OpenViking bootstrap/config helpers
- `scripts/`: deploy, backup, restore, health, and promotion helpers
- `docs/`: runbooks, verification notes, and setup docs

## Environment Model

- Local coding happens in a feature worktree.
- Local messy/manual validation can happen in `LifeOS-clean`.
- VPS should be split into `staging` and `prod`.
- Do not use production as first integration test.
- Prefer sanitized or backupable data for staging validation.

## Default Agent Behavior

- If task is a code change, assume the correct home is a clean feature worktree.
- If current tree is dirty, avoid risky branch/promotion operations until the user confirms intent.
- Prefer reading existing runbooks before inventing new commands.
- Keep edits scoped to the repo/worktree that the user is actively using.
- For VPS validation and promotion, follow [docs/FEATURE_STAGING_PLAYBOOK.md](docs/FEATURE_STAGING_PLAYBOOK.md) and [docs/DEV_VPS_WORKFLOW.md](docs/DEV_VPS_WORKFLOW.md).

## Common Commands

```bash
git worktree list
git status --short --branch
./scripts/new_feature_worktree.sh my-feature-slug
./scripts/startup_self_check.sh
docker compose ps
curl http://localhost:8100/api/health
curl http://localhost:8100/api/readiness
```

Quick start for a fresh feature worktree:

- run `./scripts/new_feature_worktree.sh my-feature-slug`
- read [docs/NEW_FEATURE_WORKTREE.md](docs/NEW_FEATURE_WORKTREE.md) for the short flow

## Deployment Flow

1. Develop in feature worktree.
2. Run local tests and smoke checks.
3. Validate on VPS staging with production-like configuration.
4. Promote only after staging passes.

## Safety Rules

- Keep `LifeOS-main-merge` clean.
- Do not treat `LifeOS-clean` as the canonical clean source.
- Backup before restore, promote, or risky deploy steps.
- Be careful with scripts that change git state, especially `scripts/restore.sh`.
- Do not rely on production data for first-pass experimentation.

## Session Bootstrap

For a new Codex session, a good opening instruction is:

```text
Read AGENTS.md and docs/SYSTEM_SETUP.md, then continue task X.
```
