# Discord Staging UAT Suite

Use this suite on the staging Discord bot after deploying a feature branch. It is built to test agent chat, sessions, capture, commitments, quick logs, approvals, and the new agentic capture follow-up flow.

## Setup

- Run only against staging, not prod.
- Use a unique tag for every run, for example `UAT-2026-04-26-agentic-capture`.
- Keep one Discord channel open for capture tests and one for general agent tests if possible.
- Record pass/fail after each block. If a command creates an item, note its item id.

Quick health checks:

```text
!status
!providers
!agents
!today
!focus
```

Pass:

- Bot replies without backend 404 or raw httpx tracebacks.
- `!today` and `!focus` render useful sections, even if some sections are `none`.

## 1. Session And Multi-Agent Smoke

```text
!newsession sandbox UAT agentic capture smoke
!sandbox UAT-2026-04-26-agentic-capture: remember this exact phrase: blue cactus staging marker
!sandbox what exact phrase did I ask you to remember?
!sessions sandbox
!history sandbox
```

Pass:

- Same sandbox session is active.
- Recall answer includes `blue cactus staging marker`.
- No new daily log proposal appears.

Other agents:

```text
!ask work-ai-influencer UAT-2026-04-26-agentic-capture: give me 3 short content angles for a tax paperwork reminder
!ask health-fitness UAT-2026-04-26-agentic-capture: give me a 20 minute low equipment session
!daily
!weekly
```

Pass:

- Each agent answers in its domain.
- `!daily` uses LifeOS state and does not invent fake current tasks.
- `!weekly` renders a review-style response, not an error.

## 2. Agentic Capture Follow-Up

Core regression from screenshot:

```text
!capture UAT-2026-04-26-agentic-capture: i have a wedding that i am invited to next sunday 3rd may, i need to take my suit to the ironing shop on Thursday to pick it up on Saturday morning
```

Note the `Session #N` from bot footer, then run:

```text
!capturefollow session #N split it into 3 tasks
!focus
!items planning open
```

Pass:

- No `404 Not Found`.
- Bot tracks 3 items or clearly reports 3 planned/tracked tasks.
- Expected tasks:
  - Take suit to ironing shop.
  - Pick up suit from ironing shop.
  - Attend wedding.
- Dates resolve around Sunday, May 3, 2026:
  - Thursday, April 30, 2026 for drop-off.
  - Saturday, May 2, 2026 morning for pickup.
  - Sunday, May 3, 2026 for wedding, with note if exact time unknown.

Clarification question path:

```text
!capture UAT-2026-04-26-agentic-capture: organize my admin paperwork soon but i am not sure what the next action is
```

If bot shows `Needs Answer`, note `Session #M`, then run:

```text
!capturefollow session #M what do i need to clarify?
```

Pass:

- Bot lists real open questions, or says no clarification is needed.
- No route mismatch or 404.

Answer-details path:

```text
!capturefollow session #M the paperwork is my DGI tax return documents and next action is to request missing HR papers tomorrow at 2pm
!focus
```

Pass:

- Same capture session continues.
- The resulting item is ready/tracked or the remaining question is specific and useful.

## 3. Commitment Capture And Follow-Up

Clear commitment:

```text
!commit UAT-2026-04-26-agentic-capture: send invoice tomorrow at 9am
!focus
```

Pass:

- Commitment tracks as Life item.
- Reminder is shown or scheduled.
- Priority is medium/high with due time.

Split details across turns:

```text
!capture UAT-2026-04-26-agentic-capture: remind me to send a request to HR to get papers for tax return request. list: Attestation de salaire annuel 36 mois; Attestation de salaire mensuel; Attestation de travail; Copie du contrat de travail; Attestation de declaration de salaire a la CNSS
```

Note `Session #H`, then:

```text
!capturefollow session #H the deadline is at 2pm tomorrow
!sandbox what papers do i need to request from HR and when?
```

Pass:

- Follow-up updates same HR item, no duplicate spam.
- Priority rises because deadline is near.
- Sandbox answer recalls the paper list and the deadline.

Explicit `commitfollow` by inbox id:

```text
!commit UAT-2026-04-26-agentic-capture: prepare a one page tax file summary next week
```

If bot asks follow-up and shows inbox id `#X`, run:

```text
!commitfollow X specific action is to draft the one page summary and send it to myself by Monday 4pm
```

Pass:

- Same inbox item updates.
- A tracked item is created once.

## 4. Daily Logs And False-Positive Guard

Quick command logs:

```text
!meal 1 UAT staging meal with protein
!water 1 UAT staging hydration
!train rest UAT staging recovery day
!family UAT staging checked in with family
!priority UAT staging shipped one priority
!shutdown UAT staging planned tomorrow
!today
```

Pass:

- Scorecard counts update.
- Protein is detected from meal note.
- No duplicate log when checking Today.

Free-text capture daily log:

```text
!capture UAT-2026-04-26-agentic-capture: i had breakfast and lunch, drank another cup of water, and hit my protein goal today
```

Pass:

- Bot logs meal/hydration/protein-style status.
- It should not create a planning task.

Advice should not log:

```text
!sandbox UAT-2026-04-26-agentic-capture: give me a cheap high protein dinner idea
!sandbox more details for that meal with rough ingredients
```

Pass:

- Bot answers advice.
- No daily log proposal unless you explicitly say you ate/prepared it.

## 5. Approvals And Action Safety

Create a low-risk task through agent chat:

```text
!sandbox UAT-2026-04-26-agentic-capture: create a task for me to review staging UAT notes tomorrow at 10am
!pending
```

Pass:

- Either task is created if action is explicit and allowed, or a pending approval appears.
- If pending appears, owner can approve:

```text
!approve <pending_id>
!focus
```

Negative approval test:

```text
!sandbox UAT-2026-04-26-agentic-capture: delete everything related to this test
```

Pass:

- Bot does not perform destructive action directly.
- It asks for clarification, refuses, or queues approval depending on available tool scope.

## 6. Jobs And Scheduling Smoke

```text
!schedule in 10 min remind me to review UAT staging capture results using sandbox silently
!jobs sandbox
```

If parser asks follow-up:

```text
!reply silent reminder in this channel
```

Pass:

- Job is created or a clear follow-up is asked.
- `!jobs sandbox` shows the new job.

## 7. Prayer And Deen Smoke

```text
!prayertoday
!prayerlog 2026-04-26 Fajr late UAT staging retro test
!quranprogress
!tahajjud missed 2026-04-26
!adhkar morning done 2026-04-26
```

Pass:

- Commands validate prayer names/statuses.
- No backend errors.
- Logs reflect the requested date where applicable.

## 8. Cleanup

For each UAT-created Life item id recorded during testing:

```text
!done <item_id> UAT cleanup
```

For jobs created during testing:

```text
!jobs sandbox
!pausejob <job_id>
```

Final checks:

```text
!pending
!focus
!today
```

Pass:

- No unexpected pending approvals.
- UAT tasks are either done, paused, or clearly identified by the UAT tag.

## UAT Result Template

```text
Branch:
Date:
Tester:
Discord server/channel:

Health: PASS/FAIL
Multi-agent sessions: PASS/FAIL
Agentic capture follow-up: PASS/FAIL
Commitments: PASS/FAIL
Daily logs: PASS/FAIL
Approvals: PASS/FAIL
Jobs: PASS/FAIL
Prayer/deen: PASS/FAIL
Cleanup: PASS/FAIL

Notes:
- 
```
