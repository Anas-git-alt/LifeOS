# Updated Staging UAT - Agentic Capture Follow-up

Use after deploying `codex/agentic-capture-followup` to staging on April 27, 2026.

## Reset First

Staging memory should be cleared before this rerun so old Discord/session memory does not contaminate recall checks.

## Focused Rerun

### 1. Wedding Split

```text
!capture UAT-2026-04-27-agentic-capture: i have a wedding that i am invited to next sunday 3rd may, i need to take my suit to the ironing shop on Thursday to pick it up on Saturday morning
!capturefollow session #N split it into 3 tasks
!items planning open
```

Pass:

- Creates exactly these three planning tasks:
  - Take suit to ironing shop.
  - Pick up suit from ironing shop.
  - Attend wedding.
- Drop-off resolves to Thursday, April 30, 2026.
- Pickup resolves to Saturday, May 2, 2026 morning.
- Wedding resolves to Sunday, May 3, 2026, with note if exact time unknown.
- No unrelated health, sleep, family, or generic wedding-planning tasks.

### 2. Admin Clarification

```text
!capture UAT-2026-04-27-agentic-capture: organize my admin paperwork soon but i am not sure what the next action is
!capturefollow session #M what do i need to clarify?
```

Pass:

- Bot lists useful questions:
  - paperwork category
  - concrete next action
  - deadline
  - person/system involved

### 3. HR Papers Recall

```text
!capture UAT-2026-04-27-agentic-capture: remind me to send a request to HR to get papers for tax return request. list: Attestation de salaire annuel 36 mois; Attestation de salaire mensuel; Attestation de travail; Copie du contrat de travail; Attestation de declaration de salaire a la CNSS
!capturefollow session #H the deadline is at 2pm tomorrow
!sandbox what papers do i need to request from HR and when?
```

Pass:

- Same capture session continues; no duplicate spam.
- Recall includes the document list.
- Recall includes deadline, with local Africa/Casablanca interpretation or UTC equivalent.

### 4. Timezone Display

```text
!commit UAT timezone: remind me tomorrow at 9am to check staging
!commit UAT timezone: remind me tomorrow at 2pm to check staging
!commit UAT timezone: remind me Monday 4pm to check staging
```

Pass:

- Commitment embed shows due local time plus UTC equivalent.
- Reminder line also shows local Africa/Casablanca time plus UTC equivalent.
- No UTC-only display that hides timezone conversion.

### 5. Laptop Bag Semantic Guard

```text
!capture UAT-2026-04-27-agentic-capture: my laptop bag zipper is broken and I need to repair it before travel
```

Pass:

- Creates or tracks `Repair laptop bag zipper before travel`.
- Domain is planning/logistics.
- No unrelated health, bedtime, family, or generic fake task appears.

## WebUI Verification Still Needed

Discord screenshots alone do not prove these:

- Memory Ledger source/status/why-saved fields.
- Archive filter behavior.
- Restore behavior.
- WebUI session history matching Discord.
- Audit view showing resolved action paths.

Run these in WebUI after Discord rerun before promotion.
