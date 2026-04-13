# LifeOS Test And Cleanup Report

Date: 2026-04-13

## Scope

This report covers:

- local repo validation and fixes needed to make the stack/test path reliable
- live VPS smoke checks against the running deployment
- user-side test steps for WebUI and Discord
- repo cleanup and data-layout recommendations

## What I Validated

### Local repo

- `backend` tests: `65 passed`
- `discord-bot` tests: `12 passed`
- `webui` unit tests: `6 passed`
- `webui` production build: passed
- Docker stack:
  - `openviking`: healthy
  - `tts-worker`: healthy
  - `backend`: healthy after migration fix
  - `webui`: healthy on local override port `3101`
  - `discord-bot`: online and connected

### VPS

Validated against the real host and live secrets.

- Docker services:
  - `backend`: healthy
  - `webui`: healthy
  - `discord-bot`: up
  - `openviking`: healthy
  - `tts-worker`: healthy
- Backend:
  - `/api/health`: healthy
  - `/api/readiness`: ready
  - `/api/events/auth`: returns cookie
  - `/api/events`: streams SSE events
  - `/api/tts/health`: OK
  - live jobs API create/pause/resume/delete: passed
  - live agent chat against `sandbox`: passed, returned `LIVE_OK`
- WebUI integration path:
  - homepage served through SSH tunnel on `127.0.0.1:3100`
  - SSE auth and stream worked through the backend tunnel
  - core data endpoints returned valid data: agents, providers, profile, prayer dashboard
- Discord integration path:
  - bot connected to Discord gateway
  - all cogs loaded
  - bot successfully called backend reminder/nudge endpoints continuously without errors in the sampled logs

## Current Integration Inventory

### Configured on VPS

- Discord bot token
- Discord guild ID
- Discord owner IDs
- API secret
- OpenRouter
- NVIDIA
- GitHub token + repo
- Brave search
- OpenViking API key
- OpenViking embedding API key
- OpenViking VLM API key
- TTS worker URL

### Not configured on VPS

- Google API key
- OpenAI API key

### Provider status reported by the app

- `openrouter`: available
- `nvidia`: available
- `google`: unavailable
- `openai`: unavailable

## Issues Found

### Fixed in this repo

1. Old SQLite databases could fail backend startup because `scheduled_jobs` schema upgrades were not applied defensively enough.
2. Backend test runs were brittle because they depended on ambient local state instead of an isolated test database.
3. Session archive restore compared naive and aware datetimes.
4. Scheduler and jobs router assumed `next_run_time` always exists on scheduler job objects.
5. Ignore rules did not cover the WSL/Windows `:Zone.Identifier` artifact form.

### Still worth addressing

1. The repo still contains tracked `:Zone.Identifier` files from Windows metadata.
2. The repo also has ad-hoc debug scripts in `backend/` root (`test_db.py`, `test_orchestrator.py`, `test_search.py`) that look like tests but are really manual scripts.
3. Local-dev env handling is still conceptually messy:
   - Docker uses `.venv/.env`
   - local commands in the README imply running services outside Docker
   - the same env values contain container-only paths like `/app/storage/...`
4. Runtime/user data is split across multiple top-level places:
   - `storage/`
   - `backend/storage/`
   - `.venv/.env`
   - `tmp/`
   - `output/`
5. There is no single canonical "where agents should look first for user state" contract.

## User-Side Test Plan

### WebUI

1. Open the tunneled UI:
   - `http://127.0.0.1:3100`
2. Paste `API_SECRET_KEY` when prompted.
3. Verify these pages load without refresh loops:
   - `Mission Control`
   - `Today`
   - `Prayer`
   - `Quran`
   - `Life Items`
   - `Agents`
   - `Jobs`
   - `Approvals`
   - `Providers`
   - `Profile`
   - `Settings`
4. Confirm live data is present:
   - `Mission Control` shows healthy/ready
   - `Providers` shows `openrouter` and `nvidia` available
   - `Profile` shows your real timezone/city
   - `Prayer` dashboard renders summary/day rows
5. Create a test job in `Jobs`:
   - create
   - pause
   - resume
   - delete
6. In `Agents`, open `sandbox` and send:
   - `Reply with exactly: LIVE_OK`
   - expected result: `LIVE_OK`
7. Leave the UI open for 10-20 seconds and confirm `Mission Control` updates without a hard refresh.

### Discord

In your server, run these in order:

1. `!status`
2. `!agents`
3. `!today`
4. `!prayertoday`
5. `!pending`

Then test one safe agent chat:

- `!sandbox Reply with exactly: DISCORD_OK`

Expected:

- the bot replies quickly
- no approval is created
- no command errors appear

Then test one safe automation lifecycle:

1. `!schedule every weekday at 7:30 remind me to stretch in #fitness-log using health-fitness`
2. `!jobs`
3. `!pausejob <id>`
4. `!resumejob <id>`
5. `!jobruns <id>`

Optional voice smoke:

1. `!joinvoice sandbox`
2. `!speak sandbox testing voice output`
3. `!interrupt`
4. `!leavevoice`

## Cleanup Recommendation

### Short answer

Yes to a single top-level user-data root.

No to dumping everything into one flat folder.

The cleanest version is:

- one canonical top-level `data/`
- clear subfolders by responsibility
- one small manifest/index file that agents can read first

### Recommended target layout

```text
apps/
  backend/
  discord-bot/
  webui/
services/
  tts-worker/
infra/
  openviking/
ops/
  scripts/
docs/
skills/
data/
  user/
    profile/
    life/
    prayer/
    quran/
  memory/
    sqlite/
    openviking/
  jobs/
  workspace/
    archives/
    mirrors/
  models/
    tts/
  exports/
  tmp/
  manifest.json
```

### Why this is better than one giant shared folder

- Agents need predictability more than flatness.
- A single root like `data/` is good.
- Inside that root, stable subpaths are better than one mixed pile of files.
- Keep canonical structured state in one place, then let agents read `data/manifest.json` first to discover the rest.

### What should be canonical

- relational state: SQLite
- semantic memory/indexes: OpenViking
- file mutation rollback history: workspace archives
- human-readable coordination index: `data/manifest.json`

### Suggested `manifest.json`

This should include:

- current user profile path
- current database path
- current OpenViking data root
- workspace archive root
- latest export/report paths
- schema version
- last updated timestamp

That gives agents one reliable entry point without forcing all data into the same physical format.

## Cleanup Phase 1 Implemented

The following phase-1 cleanup work has now been applied in the repo:

- added a canonical `data/` runtime root with `data/README.md`
- backend now writes `data/manifest.json` at startup as a single coordination index
- if `data/` is not writable on a host yet, backend falls back to `storage/manifest.json` instead of failing startup
- backend path resolution now supports safe legacy fallback to `storage/` on existing deployments
- Docker now mounts `./data` into backend and TTS worker for the new contract
- backup/verify scripts now detect the active database path via manifest or fallback search
- ad-hoc backend root scripts were moved into `scripts/manual/`
- tracked `:Zone.Identifier`, stray runtime DB, and generated artifact files were removed from git

## Recommended Cleanup Order

1. Remove tracked `:Zone.Identifier` files from git.
2. Move manual debug scripts out of `backend/` root into `scripts/manual/` or `tools/debug/`.
3. Standardize on one runtime root:
   - rename `storage/` to `data/` or explicitly document `storage/` as the canonical runtime root
4. Eliminate `backend/storage/` if it is only leftover local state.
5. Split env files by purpose:
   - `.venv/.env.compose`
   - `.venv/.env.local`
   - `.venv/.env.test`
6. Keep generated/test-only output out of top-level clutter:
   - `tmp/`
   - `output/`
   - local venvs
7. Add one small architecture doc for "where agent-visible state lives".

## Best Next Refactor

If you want the highest-value cleanup with the lowest risk, do this next:

1. Make `storage/` the only runtime root, or rename it to `data/`.
2. Move all user/runtime state under that one root.
3. Add `storage/manifest.json` or `data/manifest.json`.
4. Separate Docker env from local env.
5. Remove Windows metadata files and root-level debug scripts.

That gives you cleaner operations, cleaner onboarding, and much better agent-to-agent discoverability without forcing a risky rewrite of the actual persistence model.
