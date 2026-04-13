# Runtime Storage

Keep runtime state in `storage/`, but do not commit it.

Tracked files in this directory are intentionally limited to:

- `storage/init.sql`
- `storage/README.md`
- `storage/.gitkeep`

Everything else here is local or server-specific state, including:

- SQLite databases
- OpenViking indexes and memory data
- backups
- workspace archives
- TTS caches

This keeps development checkouts clean while preserving user data on the VPS.
