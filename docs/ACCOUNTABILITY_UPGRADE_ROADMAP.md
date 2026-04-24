# Accountability Upgrade Roadmap

Status date: 2026-04-22
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

Status: completed and live-validated on VPS branch

Implemented:

- Added `daily_scorecards` data model with one row per local date
- Added deterministic `POST /api/life/daily-log`
- Extended `GET /api/life/today` with `scorecard`, `next_prayer`, `rescue_plan`, `sleep_protocol`, `streaks`, and `trend_summary`
- Redesigned WebUI `Today` around scorecard first, quick logs second, then next prayer, due work, and inbox-ready items
- Added Discord quick-log commands: `!sleep`, `!meal`, `!train`, `!water`, `!family`, `!priority`, `!shutdown`
- Added accountability streaks and a 7-day trend summary
- Added rule-based rescue plan for missing anchors and overdue high-priority work
- Upgraded Discord `!today` to show scorecard, rescue state, sleep protocol, streaks, trend summary, and explicit empty states

Concrete implementation areas:

- backend model/migration work in `backend/app/models.py` and `backend/app/migrations/202604180001_daily_scorecards.sql`
- life/accountability logic in `backend/app/services/life.py`
- API routes in `backend/app/routers/life.py`
- Discord quick-log commands in `discord-bot/bot/cogs/reminders.py`
- Discord Today summary in `discord-bot/bot/cogs/agents.py`
- Today board UI in `webui/src/components/TodayView.jsx`
- automated coverage in backend, Discord bot, WebUI unit, and Playwright tests

Phase 2 user-facing result:

- one screen now shows spiritual timing, anchor metrics, rescue state, and most urgent commitments
- daily anchors can be logged from WebUI buttons or short Discord commands
- streak momentum and 7-day completion shape are visible without asking an agent
- rescue status changes without LLM dependency

### Phase 2 Open Gaps

Status: partially closed

- Discord quick logs now capture bedtime and wake time directly through `!sleep ... bed HH:MM wake HH:MM`
- Discord now has dedicated `!family` and `!priority` quick commands
- no calendar/email accountability integrations yet
- no LLM-generated rescue plans by design

### AI-Backed Commitment Loop

Status: completed and live-validated on staging

Why this shipped before broader Phase 3:

- the biggest user value gap was promises disappearing after capture
- the user needed help following up, remembering, and choosing priority under pressure
- a generic action tracker was not enough; the feature needed to use AI for clarification and coaching while keeping reminders deterministic

Implemented:

- Added Discord `!commit`, `!commitfollow`, `!snooze`, `!focuscoach`, and `!commitreview`
- Added backend `POST /api/life/commitments/capture`
- Added backend `POST /api/life/items/{id}/snooze`
- Added backend `GET /api/life/coach/daily-focus`
- Added backend `GET /api/life/coach/weekly-review`
- Added `follow_up_job_id` on Life items
- Added one linked reminder job per promoted commitment
- Added deterministic reminder rules:
  - explicit `due_at` nudges at `due_at - 2h`, clamped if too close
  - no `due_at` nudges next local day at 09:00
- Added deterministic Today ranking with `focus_reason` and `follow_up_due_at`
- Added WebUI `Commitment Radar` and `AI Focus Coach`
- Added seeded `commitment-capture` and `commitment-coach` agents using free provider defaults
- Added on-demand weekly commitment review and a scheduled Sunday 10:00 `#weekly-review` post
- Hardened AI failure modes:
  - ready prose without `[INTAKE_JSON]` can still promote
  - AI coach endpoints fall back cleanly
  - coach can only pick from backend-provided shortlist
- Hardened Discord UX:
  - follow-up messages show copyable inbox-id commands
  - `!commitfollow <inbox_id>` resolves to the right session
  - repeat follow-up reuses the same linked Life item
  - `today eod` and `tomorrow end of day` parse as real deadlines

Phase result:

- say the thing once
- AI clarifies only when useful
- system tracks it as durable state
- deterministic reminders keep it alive
- AI helps pick what matters now without inventing tasks

Open gaps:

- weekly commitment review is on-demand only; no scheduled weekly AI review yet
- no calendar/email import for promises yet
- commitment de-duplication is scoped to same inbox/session, not semantic duplicates across all history
- WebUI is review/coaching first; Discord remains primary capture surface

## Roadmap

### Phase 3: Food, Cooking, Sleep, and Training Systems

Status: in progress

Goal:

- stop relying on memory and motivation for core physical systems

Build:

- Already landed from this phase:
  - bedtime target
  - wake target
  - caffeine cutoff
  - wind-down checklist
  - sleep protocol card in WebUI Today
  - sleep log capture of bedtime and wake time in WebUI
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

1. Phase 3: meal rotation, fallback meals, grocery planning, and training-system follow-through
2. Scheduled weekly commitment review and broader pattern detection
3. Phase 4: pattern detection and reviews across all anchors
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

Continue Phase 3 from the now-shipped accountability and commitment-loop base.

Most valuable concrete pieces:

- meal rotation with fallback meals
- grocery and pantry support
- training block planner and 15-minute fallback mode
- protocol adjustments driven by the new streak and trend data

## Definition Of Success

LifeOS is successful when:

- capture is frictionless
- follow-up is intelligent
- important commitments do not disappear
- the daily board tells the truth
- the weekly review shows patterns
- your system gets simpler and more effective over time
