# LifeOS Discord Commands

This is the current bot command surface.

For staging acceptance testing, use [DISCORD_STAGING_UAT_SUITE.md](DISCORD_STAGING_UAT_SUITE.md).

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
- Agent chat is grounded on the LifeOS state packet. If Today/status context is unavailable, the backend fails closed instead of letting the model invent your habits, deadlines, or status.
- Agent chat can use web search for current external facts, product/market questions, weather, and local budget advice.
- LifeOS planning questions such as `what should i do today?` use the state packet rather than web search.
- If a chat turn contains a completed check-in, the bot proposes a daily log first. React with a check mark to apply it; reply with corrected details if the proposal is wrong.
- Follow-up questions such as `more details for the egg meal` stay in chat and should not create daily logs.

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
- `!focuscoach`
- `!profile`
- `!capture <raw life dump>`
- `!capturefollow <answer or extra context>`
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
- `!today`
- `!capture need invoice sent today, sleep routine messy, remember invoices are high leverage`
- `!add work Ship weekly KPI update`
- `!items planning open`
- `!done 42 finished before Dhuhr`
- `!goal health regain mobility consistency`
- `!goalprogress 77`

`!today` behavior:

- returns a richer embed with `Scorecard`, `Next Prayer`, `Rescue Plan`, `Sleep Protocol`, `Streaks`, `7-Day Trend`, `Commitment Radar`, `Top Focus`, `Due Today`, and `Overdue`
- empty sections now render as `none` instead of disappearing
- this command is read-only and reflects the current `Today` API state

## Raw Inbox And Auto-Priority

Use this when you do not want to decide the priority yourself. Give LifeOS messy raw input; the intake agent uses the shared Wiki context, splits actionable items, assigns AI priority scores, auto-creates clear Life items, and leaves unclear items in Inbox with follow-up questions.

- `!capture <raw life dump>`
- `!capturefollow <answer or extra context>`
- `!promotecapture <inbox_id>`

Examples:

- `!capture need invoice sent today, fix sleep routine, remember invoice follow-through is high leverage`
- `!capturefollow bedtime target should be 23:30 and wake target 07:10`
- `!promotecapture 12`

Capture behavior:

- Clear tasks, goals, habits, routines, and commitments can auto-promote into tracked Life items.
- Each created item gets `priority_score`, `priority_reason`, and Wiki context links when shared memory matches.
- Durable facts from raw input become review-required Wiki proposals instead of direct unreviewed writes.
- `!focus` uses due dates, AI priority score, and Life context so urgent/important work rises without manual priority picking.
- `!capture` is the normal intake command. It auto-routes promises/deadlines to commitment capture, durable facts/meeting notes to memory review, and tasks/goals/habits/ideas to intake.
- `!capturefollow` continues the active capture session for the same user/channel/agent. It merges answers into the existing clarifying capture rather than creating a new item.

## Commitments And Follow-Through

Use these when you said you will do something and want LifeOS to keep the loop alive.

- `!commit <message>`
- `!commitfollow <inbox_id> <answer>`
- `!commitfollow session #<session_id> <answer>`
- `!snooze <life_item_id> <time phrase>`
- `!focuscoach`
- `!commitreview`

Examples:

- `!commit send invoice tomorrow at 9am`
- `!commit create a one pager tomorrow at 10pm`
- `!commit build the Canva file deadline is today eod`
- `!commitfollow 8 specific action is to create the Canva file and add a few elements, deadline is today eod`
- `!commitfollow session #14 deadline is today end of day`
- `!snooze 10 in 2 hours`
- `!focus`
- `!focuscoach`
- `!commitreview`

Commitment behavior:

- `!commit` starts a fresh commitment-capture session.
- Clear commitments auto-promote into a tracked Life item and create one linked reminder job.
- If the AI needs more detail, use the inbox id shown in the bot message, for example `!commitfollow 8 <answer>`.
- Use `!commitfollow session #<session_id> <answer>` only when you explicitly want to continue by session id.
- Repeating follow-up on the same inbox/session reuses the same linked Life item instead of creating duplicates.
- `today eod`, `today end of day`, `tomorrow eod`, and `tomorrow end of day` are accepted commitment deadlines.
- A commitment with an explicit due time gets a reminder at `due_at - 2h`, clamped if the due time is too close.
- A commitment without a due time gets a default next-local-day 09:00 reminder.
- Marking a Life item `done` or `missed` disables its linked follow-up reminder.
- Snoozing or reopening a Life item resyncs its linked reminder.
- `!focus` is deterministic priority ranking.
- `!focuscoach` uses the commitment coach AI when available, and falls back to deterministic ranking if providers fail.
- `!commitreview` gives an on-demand weekly commitment review. The same review is auto-posted every Sunday at 10:00 to `#weekly-review`.
- Follow-up answers can split detail across turns. Example: initial capture says `on Monday`, follow-up says `before 4:30pm` and `create a case in Workday`; LifeOS combines them into one tracked item.

## Prayer, Quran, Habits, And Quick Logs

- `!prayer`
- `!prayertoday`
- `!prayerlog <YYYY-MM-DD> <prayer> <status> [note]`
- `!quran <end_page> [start_page] [note]`
- `!quranprogress`
- `!sleep [hours] [bed HH:MM] [wake HH:MM] [note]`
- `!meal [count] [note]`
- `!train [done|rest|missed] [note]`
- `!water [count] [note]`
- `!family [note]`
- `!priority [note]`
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
- `!sleep 7.5 bed 23:30 wake 07:10 solid night`
- `!sleep rough night but up for Fajr`
- `!meal 2 chicken rice`
- `!meal protein shake`
- `!train done push day`
- `!train rest sore today`
- `!water 2 after walk`
- `!family called parents`
- `!priority shipped invoice`
- `!shutdown tomorrow planned and inbox clear`
- `!adhkar morning done`
- `!tahajjud missed 2026-03-05`
- `!workout pushed legs today for 45 minutes`
- `!wife promised dinner out Friday`

Quick-log behavior:

- `!sleep` accepts leading float hours, optional `bed HH:MM`, optional `wake HH:MM`, or note-only text.
- `!meal` and `!water` accept leading integer count, default `1`.
- `!train` accepts optional first token `done`, `rest`, or `missed`; default is `done`.
- `!family` marks today's family-action anchor complete and stores optional note.
- `!priority` increments today's completed-priority count and stores optional note.
- `!shutdown` marks shutdown complete for today and stores optional note.
- Quick-log replies echo compact scorecard state: meals, water, training, priorities, and rescue status.
- Normal agent chat also detects completed quick logs from free text. It asks for check-mark confirmation before mutating Today.
- Corrections such as `remove meal keep only water` update the proposed action before execution.
- Advice/detail requests are not logs. `more details for the egg meal` is recipe chat; `meal prepared and eaten` is a meal log proposal.

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
3. Log anchors as they happen with `!sleep`, `!meal`, `!train`, `!water`, `!family`, `!priority`, and `!shutdown`.
4. Clear pending actions with `!pending`.
5. Use `!schedule` for recurring reminders you would otherwise forget.
6. Keep longer agent work in explicit sessions instead of one giant running thread.
