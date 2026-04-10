---
name: lifeos-webui-mission-control
description: Implement or plan the LifeOS WebUI Mission Control dashboard upgrade. Use when working on calm information architecture, dark-mode design tokens, widget patterns, caching/data-layer reliability, SSE real-time updates, keyboard-first accessibility, or phased rollout tasks tied to README.md, codebase.md, LOCAL_PROD_RUNBOOK.md, and RELEASE_CHECKLIST.md.
---

# LifeOS WebUI Mission Control

Follow this workflow to deliver Mission Control upgrades safely and incrementally.

## 1) Verify source of truth first

Before changing code, verify these docs and align names/headings used in implementation notes:
- `README.md` (Architecture, WebUI, Security/Auth)
- `codebase.md` (Repo Structure, WebUI routes/pages, API surface)
- `LOCAL_PROD_RUNBOOK.md` (local production run + troubleshooting)
- `RELEASE_CHECKLIST.md` (pre-release checks and smoke tests)

If any of these files do not exist yet, create a minimal stub for each before proceeding to implementation — never skip verification steps silently.

If headings differ, update references in planning notes/PR text to match actual headings.

## 2) Choose execution mode

Pick one mode based on request scope:
- **Roadmap mode**: Plan by milestone using `references/implementation-roadmap.md`.
- **Implementation mode**: Execute specific capability cards from `references/dashboard-skill-cards.md`.

## 3) Apply non-negotiable constraints

- Use only documented existing endpoints unless explicitly implementing a new endpoint proposal (for SSE).
- Preserve current token-banner auth semantics (`API_SECRET_KEY`) unless explicitly asked to change auth design.
- Keep UX calm: progressive disclosure, local widget failure boundaries, clear empty/error states.
- Keep dependencies minimal and justified.

## 4) Implement in this order

1. Baseline and guardrails (instrumentation, conventions, API endpoint verification).
2. Mission Control IA + reusable widget chrome + dark-mode semantic tokens.
3. Data layer standardization (typed API client + caching/SWR).
4. Workflow speedups (approvals mutations, drilldowns, shortcuts).
5. Real-time backbone (SSE endpoint + client hook + event-to-cache routing + coalescing).
6. Performance/a11y/release hardening and smoke checks.

Use milestone details in `references/implementation-roadmap.md`.

## 5) Use skill cards as implementation units

Treat each card in `references/dashboard-skill-cards.md` as a discrete, testable work item with:
- objective
- where it applies
- implementation recipe
- production hardening checklist
- acceptance criteria

When user asks for one improvement (example: "add realtime"), execute only the relevant card set (example: D1-D3) and keep scope tight.

## 6) Required validation pattern

For each change:
1. Run local-prod/dev flow from `LOCAL_PROD_RUNBOOK.md`.
2. Validate loading, empty, error, and recovery states.
3. Validate keyboard navigation and focus visibility on changed surfaces.
4. Validate no token leakage in logs.
5. Update `RELEASE_CHECKLIST.md` smoke checks when behavior changes.

## References

- Capability cards: `references/dashboard-skill-cards.md`
- Phased delivery plan: `references/implementation-roadmap.md`
