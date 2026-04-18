# User-Side Discord and WebUI Test Guide

Date: 2026-04-18

Purpose: manual user acceptance checks for the current `codex/obsidian-shared-memory-runtime` branch before promoting wider.

## Preconditions

- VPS or local stack is running the same branch you want to test.
- Backend, WebUI, Discord bot, OpenViking, and TTS worker are up.
- You can open the WebUI and send Discord commands in the target server.
- At least one enabled agent exists, preferably `sandbox`.

## Branch Under Test

- Branch: `codex/obsidian-shared-memory-runtime`
- Main user-visible areas touched by this validation pass:
  - agent chat warning plumbing
  - longer WebUI chat timeout for slow replies
  - WebUI pending reply state with elapsed timer
  - expanded top-level navigation coverage
  - Discord display of backend warnings
  - workspace file-list parsing fix for prompts like "list of files in docs/"

## Discord Tests

### 1. Basic agent reply

Command:

```text
!sandbox Reply with exactly: DISCORD_OK
```

Expected:

- Bot replies successfully.
- Reply content contains `DISCORD_OK`.
- No generic `503 Service Unavailable`.

### 2. Warning visibility when memory is degraded

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

Command:

```text
!work-ai-influencer In my planning memory, what time is my focus block?
```

Expected:

- Bot eventually replies instead of failing too early.
- If provider retries happen, Discord still returns final answer once backend completes.
- If warnings exist, they appear in a `Note:` line.

## WebUI Tests

### 1. Navigation smoke

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

### 2. Agent chat pending state

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

### 3. Warning banner in chat

Use same agent chat if backend returns warnings.

Expected:

- Reply still renders
- Warning text appears in a blue notice area below chat form
- Warning does not replace the actual reply

### 4. Jobs page heading and basic create flow

Open `Jobs`.

Expected:

- Heading says `Scheduled Jobs`

Then create a harmless test job with any enabled agent.

Expected:

- Form submits
- No stale expectation for old `Cron Jobs` heading

### 5. Inbox page visibility

Open `Inbox`.

Expected:

- Page renders without crash
- Existing inbox items are visible if present

### 6. Experiments page visibility

Open `Experiments`.

Expected:

- Page renders
- Provider experiment data or empty state appears normally

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
- WebUI agent chat waits beyond the old short timeout and eventually returns
- WebUI shows `Thinking...` and elapsed timer during slow requests
- Inbox and Experiments pages load
- Workspace listing prompt no longer misparses `of`

## Fail Examples To Capture

- `Chat failed: Request timed out`
- Discord `503 Service Unavailable`
- Missing `Note:` line when backend warnings exist
- Pending bubble never resolves
- Inbox or Experiments page crashes
- Prompt `list of files in docs/` produces `.of`-style filtering behavior

## Evidence To Save

- Screenshot of WebUI pending chat state
- Screenshot of final WebUI reply
- Screenshot or Discord message link for warning note
- Exact prompt used
- Agent name
- Timestamp
- If failed, browser console error or backend log snippet
