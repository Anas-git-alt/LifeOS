# User-Side Discord and WebUI Test Guide

Date: 2026-04-22

Purpose: manual user acceptance checks for the current `codex/commitment-loop-ai` branch before promoting to `main`.

## Status Of This Checklist

This checklist mixes two kinds of validation:

- `Implemented and covered locally`: feature exists in code and already has local automated coverage.
- `Still requires manual UAT`: feature may already be implemented, but this document still asks you to verify the live Discord/WebUI behavior on the deployed stack.

Already implemented and covered locally before this manual pass:

- Discord smoke commands `!status`, `!agents`, and `!today`
- Discord quick-log commands: `!sleep`, `!meal`, `!train`, `!water`, `!family`, `!priority`, `!shutdown`
- WebUI `Today` accountability board
- WebUI quick-log interactions
- WebUI pending chat state with `Thinking...`, elapsed timer, and `View request status`
- Discord warning follow-up line starting with `Note:`
- top-level WebUI navigation coverage
- Jobs page heading `Scheduled Jobs`
- AI-backed commitment capture and follow-up commands
- deterministic commitment ranking and AI focus coach fallback

Still manual in this checklist:

- real Discord command execution on the live server
- real browser rendering and interaction against the deployed WebUI
- real backend warning display under live provider/memory conditions

Latest automated verification now also includes VPS-side test runs:

- backend pytest on VPS
- Discord bot pytest on VPS
- WebUI Vitest on VPS through Dockerized Node runtime
- WebUI Playwright on VPS through Dockerized Playwright runtime

## Preconditions

- VPS or local stack is running the same branch you want to test.
- Backend, WebUI, Discord bot, OpenViking, and TTS worker are up.
- You can open the WebUI and send Discord commands in the target server.
- At least one enabled agent exists, preferably `sandbox`.

## Branch Under Test

- Branch: `codex/commitment-loop-ai`
- Main user-visible areas touched by this validation pass:
  - Today accountability board with scorecard, next prayer, rescue plan, sleep protocol, streaks, trend summary, and quick logs
  - Discord quick-log commands for sleep, meals, training, water, family, priority, and shutdown
  - richer Discord `!today` output with explicit empty-state fields
  - Discord commitment commands: `!commit`, `!commitfollow`, `!snooze`, `!focuscoach`, `!commitreview`
  - WebUI Today commitment radar and AI focus coach card
  - existing agent/session/navigation coverage that remains part of release confidence

## Latest Manual Pass Notes

Validated live by user on 2026-04-19:

- `!status`
- `!today`
- `!sleep`
- `!meal`
- `!train`
- `!water`
- `!family`
- `!priority`
- `!shutdown`
- WebUI Today/Profile flows related to the new accountability features

Follow-up change landed after that pass:

- Discord `!today` now prints scorecard, rescue plan, sleep protocol, streaks, trend summary, and explicit `none` empty states

Validated live by user on staging on 2026-04-22:

- `!commit` can create clarifying entries with copyable follow-up commands.
- `!commitfollow <inbox_id> <answer>` can promote a clarifying entry into a tracked commitment.
- Repeating follow-up on the same inbox/session no longer creates duplicate Life items.
- `deadline is today eod` is parsed as local end of day and sets a real due time.
- Linked reminder time is derived from due time minus 2 hours.
- `!items` shows the promoted commitment and due time.
- `!focus` ranks open commitments with focus reasons.

## Discord Tests

### 1. Basic agent reply

Status:

- Implemented in app
- Still requires manual UAT here

Command:

```text
!sandbox Reply with exactly: DISCORD_OK
```

Expected:

- Bot replies successfully.
- Reply content contains `DISCORD_OK`.
- No generic `503 Service Unavailable`.

### 2. Warning visibility when memory is degraded

Status:

- Implemented in app
- Still requires manual UAT here

Goal: confirm Discord now shows backend warnings instead of silently hiding them.

Command:

```text
!sandbox In my planning memory, what time is my focus block?
```

Expected:

- Main reply still appears even if memory context is degraded.
- If backend sends warnings, Discord posts a follow-up line starting with `Note:`.
- Bot does not fail whole turn just because OpenViking session save/search is flaky.

### 3. Session continuity

Status:

- Implemented in app
- Still requires manual UAT here

Commands:

```text
!sessions sandbox
!sandbox Reply with exactly: SESSION_TEST_ONE
!history sandbox
```

Expected:

- Session list returns at least one session.
- New reply is attached to active session.
- `!history sandbox` shows the recent message and response.

### 4. Long-running chat behavior

Status:

- Implemented in app
- Still requires manual UAT here

Command:

```text
!work-ai-influencer In my planning memory, what time is my focus block?
```

Expected:

- Bot eventually replies instead of failing too early.
- If provider retries happen, Discord still returns final answer once backend completes.
- If warnings exist, they appear in a `Note:` line.

### 5. Quick accountability commands

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

Commands:

```text
!sleep 7.5 bed 23:30 wake 07:10 solid night
!meal protein shake
!train rest sore today
!water 2 after walk
!family called parents
!priority shipped invoice
!shutdown tomorrow planned
```

Expected:

- Each command returns success message instead of generic error.
- Reply contains compact scorecard summary like `Meals`, `water`, `train`, `priorities`, and `rescue`.
- `!meal protein shake` marks protein context without extra prompt.
- `!train rest ...` keeps training state explicit as `rest`.
- `!sleep ... bed ... wake ...` records bedtime and wake time.
- `!family` and `!priority` update the two daily anchors that rescue planning watches.

### 6. Discord `!today` summary

Status:

- Implemented in app
- Covered locally by Discord bot automated tests
- Still useful to sanity-check manually after deploy

Command:

```text
!today
```

Expected:

- Embed title is `Today (<timezone>)`
- Embed includes `Scorecard`, `Next Prayer`, `Rescue Plan`, `Sleep Protocol`, `Streaks`, `7-Day Trend`, `Top Focus`, `Due Today`, and `Overdue`
- Empty sections render `none` instead of vanishing
- If you have open focus or overdue items, they appear in the relevant fields

### 7. Commitment capture and follow-up

Status:

- Implemented in app
- Covered locally by automated tests
- Live-validated on staging

Commands:

```text
!commit create a one pager tomorrow at 10pm
!commitfollow <inbox_id> specific action is to create the Canva file and add a few elements, deadline is today eod
!items
!focus
```

Expected:

- `!commit` either creates a tracked Life item immediately, or returns an Inbox id with a copyable `!commitfollow <inbox_id> <answer>` command.
- `!commitfollow <inbox_id> ...` processes the same inbox item instead of creating a new unrelated session.
- If the AI says the commitment is ready, backend promotes it even when the model omits the machine JSON block.
- The promoted Inbox item becomes `processed`.
- The Life item appears in `!items`.
- `today eod` or `today end of day` sets due time to local end of day.
- Linked reminder is due time minus 2 hours, unless the deadline is too close.
- Repeating follow-up on the same inbox/session reuses the same linked Life item instead of duplicating it.

### 8. AI focus coach and weekly commitment review

Status:

- Implemented in app
- Covered locally by automated tests
- Still useful to sanity-check manually after deploy

Commands:

```text
!focuscoach
!commitreview
```

Expected:

- `!focuscoach` returns `Primary`, `Why now`, `First step`, `Defer`, `Nudge`, and `Mode`.
- `Mode: ai` appears when provider call succeeds.
- `Mode: fallback` appears with a useful deterministic response when providers are unavailable or time out.
- The primary item is chosen only from existing ranked commitments.
- `!commitreview` returns wins, stale commitments, repeat blockers, promises at risk, next-week simplification, and mode.
- The same review is also scheduled weekly for Sunday 10:00 in `#weekly-review`.

## WebUI Tests

### 1. Navigation smoke

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

Open WebUI and confirm these pages load from the left nav:

- Mission Control
- Today
- Inbox
- Prayer
- Quran
- Life Items
- Agents
- Spawn Agent
- Jobs
- Approvals
- Providers
- Experiments
- Profile
- Settings

Expected:

- Each page opens without blank screen or console-visible failure.
- Heading matches selected page.

### 2. Today accountability board

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

Open `Today`.

Expected:

- Page renders scorecard stats for sleep, meals, water, training, shutdown, protein, family, priorities, and inbox-ready count.
- `Next Prayer` card renders prayer name plus start/end window, or clean fallback text.
- `Rescue Plan` card renders status badge and action list or on-track text.
- `Sleep Protocol` card renders bedtime target, wake target, caffeine cutoff, checklist, and latest logged sleep data.
- `Streaks` card renders hit/pending/miss state and current streak counts.
- `7-Day Trend` card renders average completion, best day, and recent day summaries.
- `Quick Logs` buttons render for meal, protein meal, water, training, rest day, family action, priority done, and shutdown.
- `Sleep Log` form renders with hours, bedtime, wake time, and note fields.
- Due today, overdue, top focus, and inbox-ready sections still render below new accountability cards.

### 3. Today quick-log interaction

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

On `Today`, click:

- `Water +1`
- `Priority Done`

Expected:

- Success banner appears with compact scorecard summary.
- Corresponding counts update without full page reload.
- Rescue plan card stays visible and may change status/headline.
- Buttons show temporary `Saving...` state while request is in flight.

### 4. Agent chat pending state

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

Open:

- `Agents`
- choose `sandbox` or another enabled agent
- open an existing session

Send:

```text
In my planning memory, what time is my focus block?
```

Expected while waiting:

- Temporary assistant bubble shows `Thinking...`
- Bubble has dashed/pending styling
- Status card appears under input
- Status card shows elapsed seconds
- `View request status` accordion is visible

Expected after reply:

- Pending bubble is replaced by final assistant response
- Input stays usable
- No browser-level request timeout at 12s

### 5. Warning banner in chat

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

Use same agent chat if backend returns warnings.

Expected:

- Reply still renders
- Warning text appears in a blue notice area below chat form
- Warning does not replace the actual reply

### 6. Jobs page heading and basic create flow

Status:

- Heading change is implemented and covered locally
- Create flow still requires manual UAT here

Open `Jobs`.

Expected:

- Heading says `Scheduled Jobs`

Then create a harmless test job with any enabled agent.

Expected:

- Form submits
- No stale expectation for old `Cron Jobs` heading

### 7. Inbox page visibility

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

Open `Inbox`.

Expected:

- Page renders without crash
- Existing inbox items are visible if present

### 8. Experiments page visibility

Status:

- Implemented in app
- Covered locally by automated tests
- Still requires manual UAT here

Open `Experiments`.

Expected:

- Page renders
- Provider experiment data or empty state appears normally.
- Header shows whether shadow routing is on and whether free-only mode is active.

## Workspace Prompt Regression Test

Use a workspace-enabled agent in WebUI or Discord.

Prompt:

```text
what's the list of files in docs/
```

Expected:

- Agent interprets this as a directory listing request
- It does not misread `of` as an `.of` file extension filter

## Pass Criteria

- Discord basic reply works
- Discord warning note appears when backend sends warnings
- Discord quick-log commands update scorecard state and return summary text
- Discord `!today` shows richer summary fields and explicit empty states
- WebUI Today page shows scorecard, next prayer, rescue plan, sleep protocol, streaks, trend summary, and quick logs
- WebUI Today page shows commitment radar and AI focus coach without blank-screen failures
- WebUI quick logs update counts without reload
- Discord commitment capture/follow-up creates one tracked Life item and linked reminder
- Discord commitment EOD deadlines become real due times
- `!focuscoach` and `!commitreview` degrade cleanly if AI providers are unavailable
- WebUI agent chat waits beyond the old short timeout and eventually returns
- WebUI shows `Thinking...` and elapsed timer during slow requests
- Inbox and Experiments pages load
- Workspace listing prompt no longer misparses `of`

## Fail Examples To Capture

- `Chat failed: Request timed out`
- Discord `503 Service Unavailable`
- Missing `Note:` line when backend warnings exist
- Missing Today scorecard, next prayer, or rescue plan sections
- Commitment says `Ready to track` but remains `clarifying`
- `!commitfollow <inbox_id>` creates duplicate Life items
- `today eod` does not show a due time in `!items`
- Today quick-log buttons do nothing or never leave `Saving...`
- Quick-log reply does not include updated summary
- Pending bubble never resolves
- Inbox or Experiments page crashes
- Prompt `list of files in docs/` produces `.of`-style filtering behavior

## Evidence To Save

- Screenshot of WebUI pending chat state
- Screenshot of final WebUI reply
- Screenshot of Today page scorecard/rescue plan
- Screenshot of quick-log success state after button click
- Screenshot or Discord message link for warning note
- Discord message links for at least one quick-log command
- Discord message links for `!commit`, `!commitfollow`, `!items`, `!focus`, `!focuscoach`, and `!commitreview`
- Exact prompt used
- Agent name
- Timestamp
- If failed, browser console error or backend log snippet
