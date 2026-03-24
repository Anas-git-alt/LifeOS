## 🤖 Default Agents

| Agent | Purpose | Discord Channel | Schedule |
|---|---|---|---|
| **prayer-deen** | Prayer reminders, adhkar, Quran tracker | #prayer-tracker | ~prayer times |
| **marriage-family** | Commitment tracker, date ideas, gentle reminders | #wife-commitments | Daily 9am |
| **work-ai-influencer** | Shift reminders, AI content ideas, analytics | #ai-content | Daily 1pm |
| **health-fitness** | Workout plans, meals, consistency tracking | #fitness-log | Daily 8am |
| **daily-planner** | Morning briefing, ADHD time blocks, conflicts | #daily-plan | Daily 7am |
| **weekly-review** | Sunday recap, wins/misses, next week goals | #weekly-review | Sunday 10am |
| **sandbox** | General testing agent for prompts, tools, and experiments | — | Manual |

### Example Discord Commands

```
!daily                    → Get today's schedule
!sandbox Plan my week around work + prayer
!ask prayer-deen Did I pray Dhuhr?
!ask health-fitness I did 30 min yoga today
!wife promised to get flowers tomorrow
!workout upper body push, 40 mins
!sessions sandbox         → List sandbox sessions
!newsession sandbox Focus week plan
!usesession sandbox 12
!history sandbox          → Show active session history
!clearsession sandbox     → Reset active session context
!prayer                   → Log a prayer
!prayertoday              → Show today's real prayer windows
!prayerlog 2026-03-01 Fajr late overslept
!quran 2 4               → Log Quran progress (juz + pages)
!tahajjud done           → Log tahajjud
!adhkar morning done     → Log morning adhkar
!weekly                   → Trigger weekly review
!pending                  → View approval queue
!approve 1                → Approve action #1
!reject 2 Not needed      → Reject action #2
!status                   → System health
!providers                → LLM provider status
!agents                   → List all agents
```

### Chat Sessions (WebUI + Discord)

- **WebUI**: open `Agents` → select an agent → `Chat` tab.
- Create or switch sessions from the left panel.
- Use **Clear context** to wipe only that session history.
- Session titles auto-generate from the first 1-3 prompts.
- **Discord** keeps an active session per `(guild, channel, user, agent)`:
  - `!sessions <agent>`
  - `!newsession <agent> [title]`
  - `!usesession <agent> <session_id>`
  - `!renamesession <agent> <session_id> <title>`
  - `!clearsession <agent> [session_id]`
  - `!history <agent> [session_id]`
  - `!ask` and `!sandbox` automatically use the active session.

### Deen Accountability (Prayer + Habits)

- Prayer schedule + windows: `GET /api/prayer/schedule/today`
- Prayer check-ins:
  - Real-time: `POST /api/prayer/checkin`
  - Retroactive: `POST /api/prayer/checkin/retroactive`
- Deen habits:
  - Quran: `POST /api/prayer/habits/quran`
  - Tahajjud: `POST /api/prayer/habits/tahajjud`
  - Adhkar: `POST /api/prayer/habits/adhkar`
- Weekly metrics: `GET /api/prayer/weekly-summary` (on-time rate, completion, retroactive logs, Quran, tahajjud, adhkar)
- Discord prayer reminders support reaction logging:
  - `✅` on-time, `🕒` late, `❌` missed

### Sample Daily Report

```
🌅 Good Morning! | Tuesday, Feb 27

📋 Today's Focus (3 Items):
  1. 🏋️ Morning workout — upper body (30 min)
  2. 🤖 Draft AI workflow post for LinkedIn
  3. 💕 Pick up flowers for wife

⏰ Time Blocks:
  07:00 – 07:30  🕌 Fajr + morning adhkar
  07:30 – 08:00  🏋️ Workout
  08:00 – 13:00  🏠 Personal time
  13:30 – 14:00  🍽️ Lunch + prep for shift
  14:00 – 00:00  💼 Work shift
  (Prayers embedded: Dhuhr 12:30, Asr 15:45, Maghrib 18:15, Isha 19:45)

❤️ Family: Remember the flowers!
```

### Sample Weekly Report

```
📊 Weekly Review — Feb 23–27

✅ Wins:
  • Prayed all 5 prayers on time: 4/5 days
  • Prayer on-time accuracy: 29/35 (82.86%)
  • Retroactive prayer logs: 2
  • Quran progress: max juz 8, pages read this week 46
  • Tahajjud: 4/4 target
  • Adhkar consistency: morning 6/7, evening 5/7
  • Published 2 AI content posts
  • Completed 3 workouts

⚠️ Missed:
  • Forgot date night on Thursday
  • Skipped Friday workout

📈 Streaks: Prayer 4 days | Workout 3 days | Content 5 days

🎯 Next Week Focus:
  1. Schedule date night for Wednesday
  2. Try morning workouts (before shift)
  3. Draft video script for AI agents tutorial
```

---