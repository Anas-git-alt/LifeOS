---
name: lifeos-maintenance
description: Maintain a local LifeOS production deployment safely. Use when cleaning test/smoke artifacts from SQLite, auditing production-vs-test jobs/agents, backfilling or improving cron job descriptions, or standardizing scheduler metadata without deleting real user data.
---

# LifeOS Maintenance

Use this skill for production-safe maintenance of LifeOS data and cron metadata.

## Workflow

1. Back up `storage/lifeos.db` before mutation.
2. Inspect current state (jobs, agents, pending actions, logs).
3. Run cleanup in dry-run mode first.
4. Apply cleanup only after reviewing planned deletions.
5. Backfill or improve cron descriptions.
6. Re-inspect and confirm only production rows remain.

## Commands

Use the bundled script:

```bash
python3 skills/lifeos-maintenance/scripts/lifeos_db_maintenance.py --db storage/lifeos.db inspect
```

Dry-run cleanup of known test patterns (`smoke-`, `proposal-`, `temp-`):

```bash
python3 skills/lifeos-maintenance/scripts/lifeos_db_maintenance.py --db storage/lifeos.db cleanup-test-artifacts
```

Apply cleanup:

```bash
python3 skills/lifeos-maintenance/scripts/lifeos_db_maintenance.py --db storage/lifeos.db cleanup-test-artifacts --apply
```

Add extra custom test prefixes when needed:

```bash
python3 skills/lifeos-maintenance/scripts/lifeos_db_maintenance.py --db storage/lifeos.db cleanup-test-artifacts --prefix scratch- --apply
```

Dry-run description backfill:

```bash
python3 skills/lifeos-maintenance/scripts/lifeos_db_maintenance.py --db storage/lifeos.db fill-job-descriptions
```

Apply description backfill:

```bash
python3 skills/lifeos-maintenance/scripts/lifeos_db_maintenance.py --db storage/lifeos.db fill-job-descriptions --apply
```

## Safety Rules

- Default to dry-run for cleanup and description updates.
- Never delete rows without a backup.
- Target only known test artifacts unless the user explicitly confirms broader deletion scope.
- Prefer deterministic filtering (`name/source/created_by`) over free-text matching.

## Description Quality

When editing cron descriptions, follow:
- intent + target + expected outcome
- one clear sentence

For examples and wording patterns, read:
- `references/description-pattern.md`
