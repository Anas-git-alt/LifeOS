# New Feature Worktree

Use this when starting a fresh feature from clean `main`.

## One Command

From any LifeOS worktree:

```bash
cd /home/anasbe/LifeOS-feature-next
./scripts/new_feature_worktree.sh calendar-upgrade
```

That script will:

1. refresh `/home/anasbe/LifeOS-main-merge` to latest `origin/main`
2. create branch `codex/calendar-upgrade`
3. create worktree `/home/anasbe/LifeOS-feature-calendar-upgrade`

## After Creation

```bash
cd /home/anasbe/LifeOS-feature-calendar-upgrade
git status --short --branch
```

Then do normal flow:

1. make changes in that feature worktree
2. test locally
3. deploy branch to staging
4. promote to `main` after staging passes

## Notes

- keep `/home/anasbe/LifeOS-main-merge` clean
- do not start new features from `/home/anasbe/LifeOS-clean`
- if a branch or folder with the same slug already exists, the script stops instead of guessing
