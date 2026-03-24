# LifeOS WebUI Mission Control Implementation Roadmap (0-6 Weeks)

## Mission
Upgrade LifeOS WebUI into a calm, local-first mission-control dashboard with realtime updates and no manual refresh.

## Guardrails
- Keep docs aligned with: `README.md`, `codebase.md`, `LOCAL_PROD_RUNBOOK.md`, `RELEASE_CHECKLIST.md`.
- Use documented endpoints only, except explicit new SSE proposal work.
- Keep auth semantics compatible with current token banner workflow.

## Milestone 0 (Days 1-3): Baseline and guardrails
- Verify current pages/routes and API payload shapes.
- Identify styling and data-fetching patterns already in use.
- Add minimal dev instrumentation for render behavior.
- Add Mission Control smoke item to release checklist if missing.

## Milestone 1 (Week 1): IA and design system foundation
- Add Mission Control route and shell layout.
- Add reusable widget chrome and state handling primitives.
- Add dark-first semantic tokens and consistent focus rings.
- Add density control in Global Settings.

## Milestone 2 (Week 2): Data layer and initial widgets
- Standardize API client + error taxonomy.
- Add caching/SWR behavior for widget data.
- Wire Mission Control widgets to documented endpoints.
- Add last-updated timestamps and stale indicators.

## Milestone 3 (Week 3): Workflow speedups
- Add approvals decide actions with optimistic rollback.
- Improve jobs and agents summaries + drilldowns.
- Add keyboard shortcuts for key navigation paths.
- Virtualize heavy logs where needed.

## Milestone 4 (Weeks 4-5): Realtime backbone (SSE)
- Add backend SSE endpoint (`/api/events` proposed).
- Emit domain events from jobs/approvals/system/agents/today/settings flows.
- Add frontend `useEventStream` hook and event router.
- Add buffering/coalescing for burst event handling.
- Show connected/disconnected status in Mission Control.

## Milestone 5 (Week 6): Hardening and release
- Validate performance under burst load.
- Validate keyboard-only usage and focus safety.
- Validate failure modes: backend down, wrong token, stream reconnect.
- Expand release checklist with realtime smoke tests.

## Definition of done
- Widget-local loading/empty/error/recovery behavior is consistent.
- Mission Control stays updated live for key domains without manual refresh.
- Existing pages remain stable and navigable.
- New dependencies are minimal and justified.

