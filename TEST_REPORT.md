# WebUI Test Report (2026-03-03)

> Historical report only.
> Current verification status lives in [docs/VERIFICATION_2026-04-14.md](/wsl.localhost/Ubuntu/home/anasbe/LifeOS-clean/docs/VERIFICATION_2026-04-14.md).

## Pages tested
- Home / Mission Control
- Today
- Prayer
- Quran
- Life Items
- Agents
- Spawn Agent
- Jobs
- Approvals
- Providers
- Profile
- Settings

## Findings from Playwright MCP exploration
- `401 Unauthorized` console/network errors on initial load when no token was set.
- Sidebar connection state always appeared connected, even when API token was missing.
- Status semantics were inconsistent in a few places:
  - Token banner "Not saved" used warning styling instead of error/disconnected styling.
  - Realtime reconnecting state used warning styling instead of problem styling.
  - Health badge mapping treated unknown/degraded as warning instead of failure.
- Alignment inconsistencies in form/status-heavy pages:
  - Checkbox/toggle visuals used browser defaults and did not align with status semantics.
  - Jobs cards had mixed inline spacing/alignment for summary/actions.
  - Status/error/success messages were styled inconsistently per component.
- Backend issue observed during manual run:
  - `GET /api/prayer/habits/quran/progress` returned `500` on the live local stack (`http://localhost:3100`).

## Fixes applied
- Added token-aware connection behavior:
  - Sidebar now shows `Workspace connected` (green) or `Workspace disconnected` (red).
  - Mission Control protected widgets are token-gated and show clear "Set token" empty states when disconnected.
- Improved token validation flow:
  - Token validation now uses authenticated endpoint (`/settings`) instead of `/health`.
  - Invalid token clears local token and keeps disconnected state.
- Standardized green/red status semantics:
  - Active/healthy/connected states map to green (`badge-approved` / `badge-active`).
  - Problem/disconnected/error states map to red (`badge-rejected`, error text).
  - Realtime reconnecting is now rendered as red/problem.
  - Health mapping updated so degraded/unknown are not shown as healthy/warn ambiguously.
- Alignment improvements:
  - Shared form/header rhythm tightened (`.form-group`, page header spacing, label/input alignment).
  - Checkbox/toggle inputs now use success accent color and consistent centering.
  - Jobs cards now use consistent layout classes for summary/actions/run logs.
  - Unified success/error message styling via shared semantic classes.

## Automated test suite updates
- Extended Playwright e2e coverage:
  - File: `webui/tests/e2e/main-flows.spec.js`
  - Covers landing page, all top-level nav pages, key status indicators, console smoke checks, and a primary jobs CTA form flow.
  - Captures per-page screenshots in Playwright output artifacts.
- Updated Playwright config:
  - File: `webui/playwright.config.js`
  - Adds local web server bootstrap for e2e (`vite` on `127.0.0.1:4173`) when `BASE_URL` is not provided.
- Updated Vitest config:
  - File: `webui/vitest.config.js`
  - Excludes `tests/e2e/**` from unit/integration test runs.

## Screenshot artifacts
- Before (captured via Playwright MCP):  
  `before-mission-control.png`, `before-jobs.png`, `before-providers.png`, `before-settings.png`
- After (captured from updated e2e smoke run):
  - `webui/test-results/main-flows-smoke-landing-n-eeb1c-icators-and-console-hygiene/after-mission-control.png`
  - `webui/test-results/main-flows-smoke-landing-n-eeb1c-icators-and-console-hygiene/after-jobs.png`
  - `webui/test-results/main-flows-smoke-landing-n-eeb1c-icators-and-console-hygiene/after-providers.png`
  - `webui/test-results/main-flows-smoke-landing-n-eeb1c-icators-and-console-hygiene/after-settings.png`

## Local run commands
- Unit/integration tests:
  - `cd webui && npm run test:run`
- E2E tests:
  - `cd webui && npm run test:e2e`
- E2E against a specific running URL (optional):
  - `cd webui && BASE_URL=http://localhost:3100 npm run test:e2e`
