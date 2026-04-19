# LifeOS Dev And VPS Workflow

This is the clean workflow going forward.

## 1. Keep only two local folders

- `/home/anasbe/LifeOS-clean`: active development repo with no committed user data
- `/home/anasbe/LifeOS - Copy`: historical local archive with your richer user history

Everything else can be treated as disposable once you are comfortable with the new flow.

## 2. Do all development in `LifeOS-clean`

- one-time setup:

```bash
git config core.hooksPath .githooks
```

- work on a feature branch
- commit normally
- the post-commit hook syncs that branch to the VPS for Discord and WebUI testing

If you need to skip one automatic VPS deploy:

```bash
LIFEOS_SKIP_VPS_SYNC=1 git commit -m "your message"
```

## 3. Test on the VPS

The VPS runs the same branch you just committed, so you can test through:

- Discord
- the WebUI through your SSH tunnel on port `3100`

Manual redeploy is also available:

```bash
./scripts/deploy_vps.sh
./scripts/deploy_vps.sh some-branch
```

If you are invoking scripts from a Windows/UNC-mounted shell and execute bits are not honored, use:

```bash
bash scripts/deploy_vps.sh
bash scripts/promote_to_main.sh
```

## 4. Promote stable work to `main`

Once the branch is stable:

```bash
./scripts/promote_to_main.sh
```

That script:

1. pushes the current feature branch
2. fast-forwards `main`
3. pushes `main`
4. redeploys the VPS to `main`

## 5. Why this stays clean

- runtime `storage/` data is no longer committed
- VPS user data stays on disk but out of git history
- fresh clones of `main` stay clean
- feature work and stable production both use the same repo history
