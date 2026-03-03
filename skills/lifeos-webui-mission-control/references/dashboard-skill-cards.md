# LifeOS WebUI Dashboard Skill Cards (Concise)

Use this file as a card library. Pick only the cards needed for the current request.

## Source-of-truth alignment (mandatory)
- `README.md`: Architecture, WebUI, Security/Auth
- `codebase.md`: Repo structure, routes/pages, API surface
- `LOCAL_PROD_RUNBOOK.md`: local prod run + troubleshooting
- `RELEASE_CHECKLIST.md`: pre-release checks + smoke tests

## Category A: Information Architecture and Calm UI

### A1 Mission Control home
- Build a Mission Control route with 5 widgets: System, Approvals, Jobs, Today, Agents.
- Use 2-column desktop / 1-column mobile layout.
- Keep top N summaries with "View all" links into existing pages.
- Add per-widget last-updated labels.
- Acceptance: each widget handles loading/data/empty/error independently.

### A2 Progressive disclosure (Focus/Expand)
- Create a reusable widget disclosure pattern (`collapsedCount`, `expandedCount`, toggle).
- Keep expanded view in-place and preserve scroll position.
- Acceptance: no refetch on expand when data is cached; toggle is `aria-expanded`.

### A3 Density controls
- Add comfortable/compact global density setting (persisted).
- Drive spacing/row/font tokens from `data-density` attribute.
- Acceptance: no clipping, readable typography, focus ring remains obvious.

## Category B: Dark-mode Design Foundations

### B1 Semantic tokens + focus ring
- Define semantic tokens: surfaces, text, border, focus, status states.
- Apply tokens to primitives (Button/Card/Input/Tabs).
- Acceptance: no new hard-coded colors outside token files.

### B2 Widget chrome system
- Standardize widget shell with header/status/actions/content slots.
- Add variants: default/warning/danger.
- Acceptance: all Mission Control widgets share one shell structure.

### B3 Shared loading/empty/error components
- Provide skeleton, empty CTA, and error-with-retry primitives.
- Use widget-local error handling, not page-wide failure.
- Acceptance: retry recovers without full page reload.

## Category C: Data Layer, Caching, Reliability

### C1 Typed API client and error taxonomy
- Use one API client with token injection, timeout, and normalized errors.
- Error types: Auth/Network/Server/Validation.
- Acceptance: auth failures return consistent token-required behavior.

### C2 SWR caching (TanStack Query or existing)
- Define stable query keys by domain.
- Render cached data first, then background refresh.
- Acceptance: no redundant refetches on simple navigation.

### C3 Safe optimistic mutations
- Use optimistic UI only for reversible actions (approvals decide).
- Disable double-submit and rollback on failure.
- Acceptance: failure restores previous UI state and surfaces error.

### C4 Large-list performance
- Keep Mission Control top-N only.
- Virtualize heavy logs in Jobs drilldown pages.
- Acceptance: large logs scroll smoothly and remain keyboard-usable.

## Category D: Real-time Backbone (No Manual Refresh)

### D1 SSE stream backbone
- Add new backend endpoint (proposal) for server->client event stream.
- Implement client `useEventStream()` hook with reconnect behavior.
- Include realtime connection status badge in UI.
- Acceptance: Jobs + Approvals update live without refresh.

### D2 Event-to-cache mapping
- Build central event router: map event types to targeted cache update/invalidate.
- Scope invalidations narrowly by entity keys/IDs.
- Acceptance: unrelated widgets do not refetch.

### D3 Backpressure and coalescing
- Buffer bursts and flush in short intervals (100-250ms).
- Coalesce latest-wins event types (health/readiness).
- Preserve ordering for log streams.
- Acceptance: burst traffic does not freeze UI.

## Category E: Keyboard-first UX and Accessibility

### E1 Keyboard-first navigation
- Ensure all actions are true buttons/links with labels.
- Keep visible focus ring and predictable tab order.
- Add scoped global shortcuts (e.g., `g h`, `g j`, `g a`, `?`).

### E2 Command palette
- Add `Ctrl/Cmd + K` command palette for route jumps and quick actions.
- Support focus trap, escape close, keyboard-only operation.

### E3 Accessible lists/tables
- Add keyboard selection model for list-heavy views.
- Keep focus stable during realtime updates.
- Ensure row actions are labeled and keyboard operable.

## Suggested execution sequence
1. A1 + B2 + B3
2. B1 + A2 + A3
3. C1 + C2
4. C3 + C4
5. D1 + D2 + D3
6. E1 + E2 + E3

