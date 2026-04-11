# Accountability Upgrade Roadmap

Status date: 2026-04-11
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

## Roadmap

### Phase 2: Daily Accountability Layer

Status: next priority

Goal:

- make Today page become a real accountability board, not only a task summary

Build:

- daily scorecard
- quick logs for sleep, meals, training, shutdown, hydration
- next-prayer plus readiness context
- rescue plan when day goes off track
- top commitments due today
- quick-start prompts for deen, health, work, and family

Target outcome:

- one glance should tell you whether today is on track spiritually, physically, and operationally

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

1. Phase 2: daily accountability layer
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

Build Phase 2 next.

Most valuable concrete pieces:

- `daily_scorecards` model and API
- quick log commands like `!sleep`, `!meal`, `!train`, `!shutdown`
- Today page redesign around scorecard plus rescue plan
- simple streak and trend summaries

## Definition Of Success

LifeOS is successful when:

- capture is frictionless
- follow-up is intelligent
- important commitments do not disappear
- the daily board tells the truth
- the weekly review shows patterns
- your system gets simpler and more effective over time
