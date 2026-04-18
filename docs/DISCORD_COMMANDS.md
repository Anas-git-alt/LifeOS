# LifeOS Discord Commands

This is the current bot command surface.

## Basics

- Prefix: `!`
- Help: `!help`
- Topic help: `!help <topic>`
- Help topics: `agent`, `sessions`, `life`, `deen`, `approvals`, `jobs`, `voice`, `system`

## Agent Chat

- `!ask <agent> <message>`
- `!sandbox <message>`
- `!agents`
- `!daily`
- `!weekly`

Examples:

- `!ask health-fitness build me a 30 minute upper body plan`
- `!sandbox summarize my options for reorganizing this repo`
- `!daily`
- `!weekly`

Notes:

- `!sandbox` is a shortcut for `!ask sandbox ...`.
- `!daily` uses `daily-planner`.
- `!weekly` uses `weekly-review`.

## Sessions

- `!sessions <agent>`
- `!newsession <agent> [title]`
- `!usesession <agent> <session_id>`
- `!renamesession <agent> <session_id> <title>`
- `!clearsession <agent> [session_id]`
- `!history <agent> [session_id]`

Examples:

- `!sessions daily-planner`
- `!newsession daily-planner Ramadan workweek`
- `!usesession daily-planner 12`
- `!renamesession daily-planner 12 Morning routine v2`
- `!history sandbox`

Session behavior:

- Active session state is scoped by guild, channel, user, and agent.
- If you switch channels, you may be in a different active session for the same agent.
- Clearing a session removes the message history for that session but keeps the session itself.
- Mentioning a session number in normal chat does not switch context. Use `!usesession <agent> <session_id>` or `!history <agent> <session_id>` when you want an older session on purpose.

## Life And Planning

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

- `deen`
- `family`
- `work`
- `health`
- `planning`

Valid status filters:

- `open`
- `done`
- `missed`

Examples:

- `!profile`
- `!add work Ship weekly KPI update`
- `!items planning open`
- `!done 42 finished before Dhuhr`
- `!goal health regain mobility consistency`
- `!goalprogress 77`

## Prayer, Quran, Habits, And Quick Logs

- `!prayer`
- `!prayertoday`
- `!prayerlog <YYYY-MM-DD> <prayer> <status> [note]`
- `!quran <end_page> [start_page] [note]`
- `!quranprogress`
- `!sleep [hours] [note]`
- `!meal [count] [note]`
- `!train [done|rest|missed] [note]`
- `!water [count] [note]`
- `!shutdown [note]`
- `!tahajjud <done|missed> [YYYY-MM-DD]`
- `!adhkar <morning|evening> <done|missed> [YYYY-MM-DD]`
- `!workout <details>`
- `!wife <note>`

Prayer names:

- `Fajr`
- `Dhuhr`
- `Asr`
- `Maghrib`
- `Isha`

Prayer statuses:

- `on_time`
- `late`
- `missed`

Examples:

- `!prayer`
- `!prayertoday`
- `!prayerlog 2026-03-01 Fajr late overslept`
- `!quran 25`
- `!quran 40 26`
- `!sleep 7.5 solid night`
- `!sleep rough night but up for Fajr`
- `!meal 2 chicken rice`
- `!meal protein shake`
- `!train done push day`
- `!train rest sore today`
- `!water 2 after walk`
- `!shutdown tomorrow planned and inbox clear`
- `!adhkar morning done`
- `!tahajjud missed 2026-03-05`
- `!workout pushed legs today for 45 minutes`
- `!wife promised dinner out Friday`

Quick-log behavior:

- `!sleep` accepts leading float hours or note-only text.
- `!meal` and `!water` accept leading integer count, default `1`.
- `!train` accepts optional first token `done`, `rest`, or `missed`; default is `done`.
- `!shutdown` marks shutdown complete for today and stores optional note.
- Quick-log replies echo compact scorecard state: meals, water, training, priorities, and rescue status.

Reminder reactions:

- Prayer reminder messages support `✅`, `🕒`, and `❌`.
- Only configured owners can log reminder reactions back into the system.

## Automation And Jobs

- `!schedule <natural language prompt>`
- `!spawnagent <natural language prompt>`
- `!reply <answer>`
- `!cancel`
- `!jobs [agent_name]`
- `!job <job_id>`
- `!pausejob <job_id>`
- `!resumejob <job_id>`
- `!jobruns <job_id> [limit]`

Examples:

- `!schedule every weekday at 7:30 remind me to stretch in #fitness-log using health-fitness`
- `!schedule tomorrow at 9am remind me to review /workspace/docs/spec.md using sandbox silently`
- `!schedule in 10 min remind me to post the recap notify in <#123456789012345678> using sandbox`
- `!schedule every monday at 10:00 remind me to review KPI notes in #analytics using work-ai-influencer`
- `!spawnagent create agent named focus-coach to keep me consistent in #planning every day at 8:00 approval auto`
- `!jobs`
- `!jobs daily-planner`
- `!job 3`
- `!pausejob 3`
- `!resumejob 3`
- `!jobruns 3 10`

How the natural-language parser currently works:

- It accepts `#fitness-log` and native Discord channel mentions like `<#123456789012345678>`.
- Native Discord mentions like `<#123456789012345678>` are the most reliable option for channel targeting.
- If you type a channel manually, use the actual slug form like `#fitness-log`. Plain-text channel names do not contain spaces.
- For jobs, it looks for an agent after `using <agent>` or `agent <agent>`.
- It accepts recurring phrases like `every day`, `every weekday`, `every monday`, or `weekend`.
- It accepts one-time phrases like `tomorrow at 9am`, `today at 18:00`, `on 2026-03-30 at 14:00`, and `in 10 min`.
- It accepts silent/background jobs with `silent`, `silently`, `background`, `no discord post`, or `no notification`.
- It accepts explicit Discord posting with `notify in <channel>` or `post in <channel>`.
- One-time job timestamps are stored in UTC and rendered back in the job timezone.
- For agent creation, it expects `named <agent-name>` and `approval auto|always|never`.
- If something is missing, the bot asks a follow-up question and you answer with `!reply ...`.
- Use `!cancel` to clear a pending follow-up flow.

## Approvals

- `!pending`
- `!approve <id>`
- `!reject <id> [reason]`

Examples:

- `!pending`
- `!approve 18`
- `!reject 21 wrong target channel`

Restrictions:

- Only users listed in `DISCORD_OWNER_IDS` can approve or reject actions.
- The same restriction applies to approval emoji reactions.

## Voice

- `!joinvoice <agent>`
- `!speak <agent> <text>`
- `!interrupt`
- `!leavevoice`

Examples:

- `!joinvoice sandbox`
- `!speak sandbox summarize today's priorities in 30 seconds`
- `!interrupt`
- `!leavevoice`

Notes:

- Voice commands require a guild voice channel.
- If you do not specify a target channel when joining, the bot uses the voice channel you are already in.
- Voice playback depends on the TTS worker and Discord Opus support being available.

## System

- `!status`
- `!providers`

Examples:

- `!status`
- `!providers`

## Suggested Daily Flow

1. Start with `!status`.
2. Run `!today` or `!daily`.
3. Log anchors as they happen with `!sleep`, `!meal`, `!train`, `!water`, and `!shutdown`.
4. Clear pending actions with `!pending`.
5. Use `!schedule` for recurring reminders you would otherwise forget.
6. Keep longer agent work in explicit sessions instead of one giant running thread.
