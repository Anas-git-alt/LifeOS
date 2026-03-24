## ⬆️ Optional Next Upgrades

- [ ] **SearXNG** self-hosted search (replace DuckDuckGo for unlimited queries)
- [ ] **Google Calendar** integration (replace calendar stub)
- [ ] **Email** integration (SMTP/Gmail API)
- [ ] **Telegram** bot adapter (reuse same backend API)
- [ ] **Voice memos** transcription (Whisper)
- [ ] **RAG** memory (ChromaDB/Qdrant for vector search)
- [ ] **Ollama** local LLM support (add as 5th provider)
- [ ] **Mobile PWA** for webUI
- [ ] **Multi-user** auth (add JWT middleware)

---

## 🔒 Security Notes

- Secrets stored in `.venv/.env` — excluded by `.gitignore`
- Approvals are risk-based (`medium/high` require approval, `low` can auto-complete)
- Docker containers run as non-root where possible
- Default localhost bindings are `127.0.0.1:3100` (webui) and `127.0.0.1:8100` (backend)
- On VPS: expose WebUI with reverse proxy and keep backend internal where possible
- API keys have minimal scopes — rotate quarterly
- **Never commit `.venv/.env`** — the backup script checks for this

### WebUI Auth + Realtime (SSE)

- Standard API calls remain token-header based: `X-LifeOS-Token: <API_SECRET_KEY>`.
- `NEW POST /api/events/auth` exchanges a valid token header for a short-lived HttpOnly cookie scoped to `/api/events`.
- `NEW GET /api/events` uses that cookie to open an SSE stream (`text/event-stream`).
- This preserves existing token semantics while handling the EventSource header limitation cleanly.
- Request logging uses path-only fields in middleware, so query-string tokens are not required for SSE auth.

---

## 📄 License

MIT — Free to use, modify, and distribute.

---

*Bismillah — Built with the intention of helping organize life for the better.* 🤲