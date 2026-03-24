### Troubleshooting Checklist

| Problem | Fix |
|---|---|
| `docker compose` not found | Run `sudo apt install docker-compose-plugin` |
| Permission denied on Docker | Run `sudo usermod -aG docker $USER && newgrp docker` |
| Bot not responding in Discord | Check `DISCORD_BOT_TOKEN` in `.venv/.env`; verify Message Content Intent is ON |
| Backend crash on startup | Run `docker compose logs backend` — usually a missing env var |
| WebUI blank page | Check `docker compose logs webui`; ensure backend is healthy first |
| Port 8100 already in use | `sudo lsof -i :8100` and kill the process, or change `BACKEND_PUBLIC_PORT` |
| Can't connect to LLM | Verify API key in `.venv/.env`; check `!providers` in Discord |
| SQLite locked error | Only one backend instance should run; `docker compose down` first |
| WSL2 can't access internet | Run `wsl --shutdown` in PowerShell, then reopen Ubuntu |
| Docker Desktop WSL integration | In Docker Desktop → Settings → Resources → WSL Integration → Enable Ubuntu |

---