# Accountability Upgrade Roadmap

Status date: 2026-04-18
Purpose: permanent product and implementation roadmap for making LifeOS a stronger accountability system

## Vision

LifeOS should become three things at once:

- Mirror: show truthful state across prayer, Quran, sleep, food, training, work, family, and follow-through.
- Coach: ask useful follow-up questions, detect patterns, and guide without guilt.
- Operator: turn messy thoughts into tasks, habits, routines, reminders, and reviews.

This roadmap is focused on building a real life operating system, not only a chat interface.

## Product Direction

Do not rely on one mega-agent.

Use:

- one intake brain for messy capture and clarification
- specialist agents for deen, planning, health, family, and work
- structured data models so conversations become durable state

## Current Reality

LifeOS already had strong foundations before this roadmap:

- seeded specialist agents
- prayer and Quran tracking
- daily planner and weekly review agents
- Discord and WebUI surfaces
- session memory and OpenViking context
- jobs, approvals, and automation support

Main gap before this work:

- life capture was too flat
- ideas and commitments could be discussed, but not reliably turned into structured accountability objects
- Today view was too thin
- there was no proper inbox workflow

## What Is Already Done

### Phase 1: Intake Backbone

Status: completed

Implemented:

- Added inbox-style intake data model and API surface
- Added `intake-inbox` agent for clarification and structuring
- Added structured extraction flow using `[INTAKE_JSON]`
- Added Discord capture flow
- Added WebUI inbox page
- Added Today page inbox summary
- Added manual promote flow from inbox entry to life item

Concrete implementation areas:

- backend intake service in `backend/app/services/intake.py`
- intake schemas in `backend/app/models.py`
- intake routes in `backend/app/routers/life.py`
- intake extraction in `backend/app/services/orchestrator.py`
- seeded intake agent in `backend/app/services/seed.py`
- Discord commands in `discord-bot/bot/cogs/agents.py`
- WebUI inbox page in `webui/src/components/InboxView.jsx`
- WebUI routing and API client updates in `webui/src/App.jsx` and `webui/src/api.js`
- Today integration in `webui/src/components/TodayView.jsx`

Phase 1 user-facing result:

- you can capture a messy thought
- agent can ask follow-up questions in the same intake session
- system stores a structured inbox item with status such as `clarifying`, `ready`, `parked`, or `processed`
- you can promote a ready inbox item into a life item

### Phase 1 Open Gaps

Status: not done yet

- no dedicated inbox analytics yet
- no bulk triage flow yet
- no automatic promotion rules yet
- no intake-specific frontend tests yet
- no deeper pattern scoring yet

### Phase 2: Daily Accountability Layer

Status: v1 implemented locally, pending live UAT and deployment

Implemented in v1:

- Added `daily_scorecards` data model with one row per local date
- Added deterministic `POST /api/life/daily-log`
- Extended `GET /api/life/today` with `scorecard`, `next_prayer`, and `rescue_plan`
- Redesigned WebUI `Today` around scorecard first, quick logs second, then next prayer, due work, and inbox-ready items
- Added Discord quick-log commands: `!sleep`, `!meal`, `!train`, `!water`, `!shutdown`
- Added rule-based rescue plan for missing anchors and overdue high-priority work

Concrete implementation areas:

- backend model/migration work in `backend/app/models.py` and `backend/app/migrations/202604180001_daily_scorecards.sql`
- life/accountability logic in `backend/app/services/life.py`
- API routes in `backend/app/routers/life.py`
- Discord quick-log commands in `discord-bot/bot/cogs/reminders.py`
- Today board UI in `webui/src/components/TodayView.jsx`
- automated coverage in backend, Discord bot, WebUI unit, and Playwright tests

Phase 2 user-facing result:

- one screen now shows spiritual timing, anchor metrics, rescue state, and most urgent commitments
- daily anchors can be logged from WebUI buttons or short Discord commands
- rescue status changes without LLM dependency

### Phase 2 Open Gaps

Status: not done yet

- no live VPS/UAT promotion recorded yet for this branch
- no streak or trend summaries yet
- no deeper food/cooking/sleep protocol layer yet
- no calendar/email accountability integrations yet
- no LLM-generated rescue plans by design

## Roadmap

### Phase 3: Food, Cooking, Sleep, and Training Systems

Status: planned

Goal:

- stop relying on memory and motivation for core physical systems

Build:

- meal rotation
- grocery planning
- pantry staples and emergency fallback meals
- protein and hydration targets
- bedtime target, wake target, caffeine cutoff, wind-down checklist
- training block planner
- fallback 15-minute workout mode
- recovery and soreness notes

Target outcome:

- less daily friction
- more consistency even on low-energy days

### Phase 4: Pattern Detection and Reviews

Status: planned

Goal:

- move from logging events to learning from them

Build:

- weekly pattern detection
- trend summaries across prayer, sleep, food, training, and task completion
- suggested protocol adjustments
- monthly life architecture review
- identify recurring blockers and system failures

Target outcome:

- system should tell you what keeps breaking and how to simplify it

### Phase 5: Full Life Operating System

Status: planned

Goal:

- unify all major life domains into one coherent accountability engine

Build:

- routines with anchors and fallback versions
- promises ledger
- role-based dashboards: Muslim, husband/father, worker, builder, athlete
- domain score weighting
- stronger long-term goal tracking
- system pruning and archive workflows

Target outcome:

- LifeOS becomes a practical structure for daily living, not only a tracker

## Priority Order

Recommended execution order:

1. finish live UAT and promotion for Phase 2 branch
2. Phase 3: food, cooking, sleep, and training systems
3. Phase 4: pattern detection and reviews
4. Phase 5: full life operating system

## Core Principles

- Inbox is not today list.
- Do not track everything.
- Track a small number of anchor metrics first.
- Misses should reduce friction, not create shame.
- Agent responses should write structured state whenever possible.
- Good accountability is truthful, kind, and actionable.

## Suggested Anchor Metrics

Start with these before expanding:

- five daily prayers
- Quran reading
- bedtime and wake time
- sleep duration
- workout done or not
- protein target hit or not
- hydration target hit or not
- one meaningful family action
- top three priorities completed or not
- shutdown routine completed or not

## Recommended Next Build

Finish Phase 2 live validation next, then start Phase 3.

Most valuable concrete pieces:

- live Discord and WebUI UAT on deployed stack
- deploy/promotion of current shared-memory plus accountability branch
- simple streak and trend summaries after ship
- deeper food, sleep, meal rotation, and training-system flows

## Definition Of Success

LifeOS is successful when:

- capture is frictionless
- follow-up is intelligent
- important commitments do not disappear
- the daily board tells the truth
- the weekly review shows patterns
- your system gets simpler and more effective over time
