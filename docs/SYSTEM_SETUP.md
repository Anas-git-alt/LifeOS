# LifeOS System Setup

This repo is organized around one daily user loop and several internal support systems.

## Daily Loop

Use one normal intake path:

1. Capture in Discord with `!capture ...` or in WebUI `Today`.
2. Let LifeOS auto-sort the input into a commitment, task/habit/goal, or memory review item.
3. Review `Today` for current focus, due work, habits, prayer context, rescue plan, and anything that needs an answer.
4. Answer only the review prompts LifeOS surfaces.

## Internal Plumbing

These systems should support the loop without becoming daily chores:

- Inbox entries store raw captures, clarification questions, and promotion drafts.
- Life Items store commitments, tasks, goals, and habits.
- Private memory ledger stores source-truth user facts/actions automatically, while Wiki proposals store curated durable memory updates for review before shared Obsidian writes.
- Jobs and agents run scheduled nudges, but all LLM output must be grounded in the LifeOS state packet.

## Worktrees

- `LifeOS-main-merge` is the clean main reference worktree.
- `LifeOS-feature-<slug>` is where implementation work happens.
- `LifeOS-clean` is for sandbox/manual validation and may be dirty.

Create new feature worktrees with:

```bash
./scripts/new_feature_worktree.sh my-feature-slug
```

## Runtime Services

- `backend`: FastAPI API, scheduler, providers, LifeOS data, prayer/Quran, workspace tools.
- `discord-bot`: primary capture, reminders, approvals, and quick logs.
- `webui`: Today review board and admin control plane.
- `openviking`: required runtime memory/search backend.
- `tts-worker`: optional local voice synthesis.

## Grounding Rule

Every agent chat and scheduled job receives a strict state packet built from Today agenda, profile/settings, pending review, recent job failures, private memory ledger search, linked item details, and shared-memory search. Agents must use that packet as source of truth and ask for clarification when facts are missing.
