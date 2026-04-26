# Agentic Grounding And Capture

Date: 2026-04-26

This note documents the simplify-grounding release: one daily loop, stricter state grounding, smarter free-text capture, and safer Discord testing.

## Daily Product Shape

LifeOS now treats `Capture -> Today -> grounded agent answer` as the normal loop.

- `!capture` and the Today capture box are the default intake path.
- Inbox, Wiki, and Life Items remain backend/review plumbing, not daily destinations.
- Today is the command center: capture, due/overdue work, top focus, habits, prayer anchors, rescue plan, Needs Answer, and Memory Review.
- `!commit` and `!meeting` remain power shortcuts, but route into the same capture model.
- Quick logs stay separate for anchors: sleep, meal, protein, water, training/rest, family, priority, shutdown, prayer, Quran.

## Grounded Agent Answers

Every normal agent call now gets a LifeOS state packet before the LLM answer.

Packet sources include:

- Today agenda and scorecard
- active, due, and overdue Life items
- pending capture clarification
- pending approvals and memory proposals
- recent job failures
- user profile: city, country, timezone, shift, settings
- relevant shared-memory hits when available

Rules:

- If state packet cannot build, agent fails closed instead of inventing status.
- Agent answers must use packet first.
- Missing facts should trigger a clarification or web search when web search is appropriate.
- Responses carry grounding metadata so UI/Discord can show whether answer was grounded.

## Agentic Tool Planning

Before final answer, LifeOS asks a small planner LLM whether the turn needs a tool.

Current behavior:

- Weather/current facts use web search.
- Product, price, used/new market, and local budget questions use web search.
- Weather defaults to user profile location when user omits city, for example Casablanca, Morocco.
- Local food and budget advice uses profile location and should prefer local currency/units.
- LifeOS planning questions such as `what should I do today?` do not use web search; they use the state packet.
- Short follow-ups can inherit intent from recent context, for example `casablanca` after `how is the weather today?`.

## Context-Aware Daily Log Detection

Daily log proposals are now AI-classified with recent session context before any approval is created.

The classifier returns one intent:

- `completed_checkin`
- `correction`
- `information_request`
- `future_plan`
- `none`

Only completed check-ins and corrections can create a confirmable daily-log action.

Examples:

- `i slept at 1:30 and woke up at 7:30, drqnk a cup of water` -> propose sleep + hydration
- `i ate enough protein` -> propose protein, not meal
- `more details for the egg meal, with per ingredient price` -> answer recipe details, no log proposal
- `meal prepared and eaten` -> propose meal
- `remove meal keep only water` -> correction proposal: hydration only

Discord approval behavior:

- Bot proposes logs first.
- User reacts with check mark to execute.
- After execution, the follow-up answer receives hidden transient context.
- Stale `React with check mark` memory is filtered so the bot does not ask for the same confirmation twice.

## Unified Capture

`POST /api/life/capture` is the facade for raw life input.

It routes automatically:

- promise, deadline, reminder, follow-up -> commitment flow
- durable fact, meeting, context -> memory proposal flow
- task, goal, habit, idea -> intake/Life Item flow
- ambiguous item -> Needs Answer
- status update with anchor signals -> quick daily-log/status handling

Compatibility endpoints remain:

- `/api/life/inbox/capture`
- `/api/life/commitments/capture`
- `/api/memory/intake/meeting`

Commitment follow-up now merges answers into the existing clarifying commitment. If original capture says `Monday` and follow-up says `before 4:30pm` plus `Workday`, LifeOS combines them and promotes the same item instead of repeating questions.

## Discord Response Shape

Known good:

- False log proposal on recipe follow-up is fixed.
- `!capturefollow` can resolve method/time answers.
- Weather can infer profile city.
- Protein-only check-in logs protein, not meal.

Known next improvement:

- Discord answers can still be too long for simple advice.
- Some source sections are noisy when search is used.
- Food advice should ask pantry constraints only when useful and stay short by default.
- Product/market advice should cite sources but keep recommendations compact.

## Manual Tests

Run on staging before prod, then smoke on prod after promotion.

### Weather

```text
!newsession sandbox
!sandbox how is the wether today?
```

Expected:

- Direct Casablanca weather if profile city is Casablanca.
- No `which city?` unless profile is missing.
- Uses web search and cites sources.

### Product Market Search

```text
!newsession sandbox
!sandbox what's the cheapest graphics card with 16gb available in new or used market?
!sandbox what would it be if i want an nvidia gpu?
```

Expected:

- Uses current market/search context.
- Explains workstation/compute vs gaming/display tradeoff.
- Cites sources.
- Does not invent exact certainty if listings vary.

### Today Planning With Logs

```text
!newsession sandbox
!sandbox what should i do today? i slept at 1:30 and woke up at 7:30, drqnk a cup of water
```

Expected:

- Proposes sleep 6h + hydration x1.
- After check-mark reaction, executes once.
- Follow-up plan does not ask to confirm same logs again.
- Plan uses LifeOS state packet, not random web ideas.

### Cheap Meal Follow-up

```text
!newsession sandbox
!sandbox give me 3 options for a cheap lunch i can make for cheap
!sandbox i want something with eggs in it since i have them on stock
!sandbox more details for the egg meal, with per ingredient price
!sandbox meal prepared and eaten
```

Expected:

- First three messages answer meal advice; no log proposal.
- Last message proposes meal x1.
- After check-mark reaction, meal count increments once.

### Commitment Follow-up

```text
!capture remind me to submit a request for tax return paper from hr on Monday
!capturefollow before 4:30pm
create a case in workday
```

Expected:

- Initial capture may ask Needs Answer for method/time.
- Follow-up resolves same capture.
- Tracked item created once.
- Due time combines Monday + 4:30pm local.
- No repeated method/time questions after answer.

## Suggested Next Steps

1. Add a Discord answer budget: default one message for ordinary advice, allow multi-part only for explicit detailed requests.
2. Add source policy: max 2 sources for food/advice, source-heavy only for market/current facts.
3. Add pantry-aware food behavior: use stated ingredients first, ask for missing constraints only when answer would be materially better.
4. Add tool result metadata in Discord footer: `grounded`, `web`, `state packet`, `daily log proposal`, `sources used`.
5. Add a regression fixture pack from real Discord transcripts so every user-discovered failure becomes a test case.
