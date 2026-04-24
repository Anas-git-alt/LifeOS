# ADR-001: Provider Router Circuit Breaker + Shadow Testing

## Status
Accepted — 2026-03-14

## Context

LifeOS relies on multiple LLM providers (OpenRouter, Nvidia, Google, OpenAI) for agent responses. The current `provider_router.py` already implements primary → fallback → exhaustive sweep logic, but has no way to:

1. **Protect against cascading failures** — a flaky provider will be retried 3 times per call with exponential back-off, blocking the response for several seconds even if other healthy providers are available.
2. **Autonomously discover cheaper/faster options** — newer, cheaper models appear frequently (e.g. Gemini Flash, DeepSeek R2) but require manual configuration changes to test in production.
3. **Track per-provider health** — there is no visibility into which providers are succeeding, failing, or slowing response times over time.

## Decision

### Circuit Breaker (`telemetry.py`)
We add a lightweight, in-memory circuit breaker per provider. If a provider accumulates ≥ 3 failures within a 60-second rolling window, its circuit is "open" and it is skipped immediately on the next request — no timeout penalty. The circuit resets automatically on the next successful call.

All call metrics (latency, token count, success/failure) are collected in a rolling window (`_ProviderWindow`) exposed via `get_provider_stats()` and a new `/api/telemetry` HTTP endpoint.

### Shadow Testing (`shadow_router.py`)
When `SHADOW_ROUTER_ENABLED=true`, a small percentage (~5%) of successful primary calls trigger an asynchronous "shadow call" to the next available provider. It is disabled by default while `FREE_ONLY_MODE=true` to protect free-provider quota. The shadow call:
- Runs entirely non-blocking via `asyncio.create_task()` — it never blocks the user's response
- Grades both outputs with a simple heuristic score (length match, non-empty, no error phrases)
- Persists the result to the `experiment_runs` DB table
- Never auto-promotes a provider — it only surfaces a promotion candidate card in the `ApprovalQueue` when the shadow wins ≥ 10 consecutive runs

### Risk Engine (`risk_engine.py`)
`classify_risk`, `infer_action_type`, and `should_require_approval` are extracted from `orchestrator.py` into a dedicated `risk_engine.py` module. The orchestrator imports these functions unchanged — no behavioral difference, just cleaner separation of concerns.

## Consequences

**Easier:**
- Provider health is visible in the WebUI for the first time
- Flaky providers no longer cause multi-second response delays for users
- Cheaper/faster model candidates are discovered and surfaced automatically
- Risk classification logic is independently unit-testable

**Harder / Trade-offs:**
- In-memory telemetry resets on restart. This is intentional — we avoid a migration cost and operator overhead. Persistent experiment history is handled by `experiment_runs` (SQLite/Postgres).
- Shadow calls add a small background CPU/memory and provider-quota cost (~5% of traffic × shadow call overhead), so operators must opt in with `SHADOW_ROUTER_ENABLED=true`.
- Circuit breaker trips (3 failures / 60s) are fairly aggressive for a personal system. This threshold is a constant that can be adjusted in `telemetry.py`.
