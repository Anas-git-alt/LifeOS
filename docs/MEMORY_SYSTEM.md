# LifeOS Memory System

LifeOS memory has two layers.

## Private Memory Ledger

The ledger auto-saves user-authored facts, actions, captures, corrections, and confirmed daily logs. It is private, append-only, and source-linked.

Examples:

- `!capture remind me to request HR tax papers...` stores the exact raw capture, including document lists.
- Confirmed daily logs store what was applied to Today.
- Useful chat facts like `I have eggs in stock` can be recalled later.

Ledger entries are also written as private Obsidian timeline notes under:

```text
private/life-timeline/YYYY-MM-DD/
```

The ledger is for recall. It is allowed to be messy because it preserves source truth.

## Reviewed Wiki Memory

Wiki memory stays review-first. Durable facts, preferences, decisions, and long-term context still go through Memory Review before becoming curated shared notes.

This keeps the visible wiki clean while the ledger prevents lost details.

## Agent Context

Every agent turn receives:

- Today state packet
- linked LifeItem and Intake raw details
- private ledger hits relevant to the question
- reviewed shared-memory/wiki hits
- pending Memory Review items

Rule: if user asks about prior details, agents must check ledger/wiki/context before asking the user to repeat.

## Backfill

After deploy, backfill open items and recent user turns:

```bash
PYTHONPATH=backend python3 scripts/backfill_memory_ledger.py --recent-days 14
```

This creates ledger entries for current open commitments and recent useful chat/capture facts.

## Manual Tests

- Capture HR tax document list, start new sandbox session, ask: `what papers did I say I need from HR?`
- Capture HR item, then run: `!capturefollow <session_id> set reminder at 1pm`
- Ask recipe details after meal advice; it must not propose a meal log.
- Confirm daily log with ✅; next agent answer must use updated Today and not ask for same confirmation again.
- Ask `what should I do today?`; answer should mention relevant ledger/wiki sources only when they matter.
