# LifeOS Discord Commands

This document lists the Discord bot commands and quick examples.

## Quick Start

- Prefix: `!`
- Main help: `!help`
- Topic help: `!help <topic>`
- Topics: `agent`, `sessions`, `life`, `deen`, `approvals`, `jobs`, `system`

## Agent Commands

- `!ask <agent> <message>`
- `!sandbox <message>` (shortcut for `!ask sandbox ...`)
- `!agents`
- `!daily`
- `!weekly`

Examples:
- `!ask daily-planner Build me a prayer-aware day plan`
- `!sandbox summarize my backend logs plan`

## Session Commands

- `!sessions <agent>`
- `!newsession <agent> [title]`
- `!usesession <agent> <session_id>`
- `!renamesession <agent> <session_id> <title>`
- `!clearsession <agent> [session_id]`
- `!history <agent> [session_id]`

Examples:
- `!sessions daily-planner`
- `!newsession daily-planner Ramadan morning routine`
- `!usesession daily-planner 12`

## Life Commands

- `!today`
- `!focus`
- `!profile`
- `!add <domain> <text>`
- `!items [domain] [status]`
- `!done <id> [note]`
- `!miss <id> [note]`
- `!reopen <id>`
- `!goal <domain> <title>`
- `!goalprogress <id>`

Valid domains:
- `deen`, `family`, `work`, `health`, `planning`

Valid item status filters:
- `open`, `done`, `missed`

Examples:
- `!add work Ship weekly KPI update`
- `!items work open`
- `!done 42 finished before dhuhr`
- `!reopen 42`
- `!goal deen Memorize Surat Al-Mulk`
- `!goalprogress 77`

## Deen and Habit Commands

- `!prayer`
- `!prayertoday`
- `!prayerlog <YYYY-MM-DD> <prayer> <status> [note]`
- `!quran <end_page> [start_page] [note]`
- `!quranprogress`
- `!tahajjud <done|missed> [YYYY-MM-DD]`
- `!adhkar <morning|evening> <done|missed> [YYYY-MM-DD]`

Prayer names:
- `Fajr`, `Dhuhr`, `Asr`, `Maghrib`, `Isha`

Prayer statuses:
- `on_time`, `late`, `missed`

Examples:
- `!prayerlog 2026-03-01 Fajr late woke up late`
- `!quran 25 10`
- `!adhkar morning done`

## Approvals Commands (Owner Only)

- `!pending`
- `!approve <id>`
- `!reject <id> [reason]`

Examples:
- `!approve 18`
- `!reject 21 invalid channel mapping`

## Automation and Jobs Commands

- `!schedule <natural language prompt>`
- `!spawnagent <natural language prompt>`
- `!reply <answer>` (continue follow-up questions)
- `!jobs [agent_name]`
- `!job <job_id>`
- `!pausejob <job_id>`
- `!resumejob <job_id>`
- `!jobruns <job_id> [limit]`

Examples:
- `!schedule every weekday at 7:30 remind me to stretch in #fitness-log using health-fitness`
- `!spawnagent create agent named study-coach to keep me focused in #planning every day at 8:00 approval auto`
- `!job 3`
- `!pausejob 3`
- `!jobruns 3 10`

## System Commands

- `!status`
- `!providers`

## Notes

- If a command returns `Unknown command`, run `!help`.
- Some actions require owner approval based on `DISCORD_OWNER_IDS`.
- `!ask` keeps per-channel, per-user active session memory for each agent.
