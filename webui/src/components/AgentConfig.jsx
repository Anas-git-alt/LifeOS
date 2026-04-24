import { useEffect, useMemo, useState } from "react";
import {
  archiveAgentSession,
  archiveAllAgentSessions,
  chatWithAgent,
  clearAgentSession,
  createAgentSession,
  getAgent,
  getAgentSessionMessages,
  getProviders,
  getWorkspaceArchives,
  getTtsModels,
  listArchivedAgentSessions,
  listAgentSessions,
  previewAgentVoice,
  renameAgentSession,
  restoreAgentSessionArchive,
  restoreWorkspaceArchive,
  syncWorkspaceResources,
  updateAgent,
} from "../api";

function formatSessionTime(value) {
  if (!value) return "No messages yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No messages yet";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatMessageTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], { hour: "2-digit", minute: "2-digit" });
}

function formatArchiveTime(value) {
  if (!value) return "Pending";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Pending";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function normalizeWorkspacePaths(rawText) {
  return String(rawText || "")
    .split("\n")
    .map((value) => value.trim())
    .filter(Boolean);
}

export default function AgentConfig({ agentName, onBack }) {
  const [agent, setAgent] = useState(null);
  const [providers, setProviders] = useState([]);
  const [ttsModels, setTtsModels] = useState([]);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [voicePreview, setVoicePreview] = useState({ loading: false, error: "", audioB64: "" });
  const [activeTab, setActiveTab] = useState("chat");
  const [archives, setArchives] = useState([]);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveMessage, setArchiveMessage] = useState("");
  const [syncingWorkspace, setSyncingWorkspace] = useState(false);

  const [sessions, setSessions] = useState([]);
  const [sessionArchives, setSessionArchives] = useState([]);
  const [sessionArchiveLoading, setSessionArchiveLoading] = useState(false);
  const [selectedSessionId, setSelectedSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatSending, setChatSending] = useState(false);
  const [chatError, setChatError] = useState("");
  const [chatNotice, setChatNotice] = useState("");
  const [chatRequestStartedAt, setChatRequestStartedAt] = useState(null);
  const [chatElapsedSeconds, setChatElapsedSeconds] = useState(0);

  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) || null,
    [sessions, selectedSessionId],
  );

  useEffect(() => {
    if (!agentName) return;
    setAgent(null);
    setSettingsMessage("");
    setChatError("");
    setChatNotice("");
    setSessions([]);
    setSessionArchives([]);
    setSelectedSessionId(null);
    setMessages([]);
    setChatInput("");
    setArchives([]);
    setArchiveMessage("");
    loadAgent();
    loadProviders();
    loadTtsModels();
    loadSessions(null);
    loadSessionArchives();
    loadArchives();
  }, [agentName]);

  useEffect(() => {
    if (!agentName || !selectedSessionId) return;
    loadSessionMessages(selectedSessionId);
  }, [agentName, selectedSessionId]);

  useEffect(() => {
    if (!chatSending || !chatRequestStartedAt) {
      setChatElapsedSeconds(0);
      return undefined;
    }

    const updateElapsed = () => {
      setChatElapsedSeconds(Math.max(0, Math.floor((Date.now() - chatRequestStartedAt) / 1000)));
    };

    updateElapsed();
    const intervalId = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(intervalId);
  }, [chatRequestStartedAt, chatSending]);

  async function loadAgent() {
    try {
      const loadedAgent = await getAgent(agentName);
      setAgent(loadedAgent);
      setForm({
        description: loadedAgent.description || "",
        system_prompt: loadedAgent.system_prompt || "",
        provider: loadedAgent.provider || "openrouter",
        model: loadedAgent.model || "",
        fallback_provider: loadedAgent.fallback_provider || "",
        fallback_model: loadedAgent.fallback_model || "",
        discord_channel: loadedAgent.discord_channel || "",
        cadence: loadedAgent.cadence || "",
        enabled: loadedAgent.enabled,
        speech_enabled: Boolean(loadedAgent.speech_enabled),
        tts_engine: loadedAgent.tts_engine || "chatterbox_turbo",
        tts_model_id: loadedAgent.tts_model_id || "chatterbox-turbo",
        voice_id: loadedAgent.voice_id || "",
        default_language: loadedAgent.default_language || "en",
        voice_instructions: loadedAgent.voice_instructions || "",
        preview_text: loadedAgent.preview_text || "Assalamu Alaikum. This is a voice preview.",
        reference_audio_path: loadedAgent.reference_audio_path || "",
        voice_visible_in_runtime_picker:
          loadedAgent.voice_visible_in_runtime_picker === undefined ? true : Boolean(loadedAgent.voice_visible_in_runtime_picker),
        workspace_enabled: Boolean(loadedAgent.workspace_enabled),
        workspace_paths_text: (loadedAgent.workspace_paths || []).join("\n"),
        workspace_delete_requires_approval:
          loadedAgent.workspace_delete_requires_approval === undefined
            ? true
            : Boolean(loadedAgent.workspace_delete_requires_approval),
        voice_params_json: {
          speed: loadedAgent.voice_params_json?.speed ?? 1.0,
          stability: loadedAgent.voice_params_json?.stability ?? 0.7,
          temperature: loadedAgent.voice_params_json?.temperature ?? 0.6,
          emotion_intensity: loadedAgent.voice_params_json?.emotion_intensity ?? 0.6,
          realtime_preferred: loadedAgent.voice_params_json?.realtime_preferred ?? true,
        },
      });
    } catch (error) {
      setSettingsMessage(`Error: ${error.message}`);
    }
  }

  async function loadArchives() {
    setArchiveLoading(true);
    try {
      const rows = await getWorkspaceArchives(agentName, 100);
      setArchives(rows || []);
    } catch (error) {
      setArchiveMessage(`Workspace archive error: ${error.message}`);
    } finally {
      setArchiveLoading(false);
    }
  }

  async function loadProviders() {
    try {
      setProviders(await getProviders());
    } catch (error) {
      // Keep agent settings editable even if providers endpoint fails.
    }
  }

  async function loadTtsModels() {
    try {
      const rows = await getTtsModels();
      setTtsModels(rows || []);
    } catch {
      setTtsModels([]);
    }
  }

  async function loadSessions(preferredSessionId) {
    try {
      const existing = await listAgentSessions(agentName);
      let nextSessions = existing;
      let nextSelectedId = preferredSessionId ?? selectedSessionId;

      if (!nextSessions.length) {
        const created = await createAgentSession(agentName);
        nextSessions = [created];
        nextSelectedId = created.id;
      } else if (!nextSelectedId || !nextSessions.some((session) => session.id === nextSelectedId)) {
        nextSelectedId = nextSessions[0].id;
      }

      setSessions(nextSessions);
      setSelectedSessionId(nextSelectedId);
      return nextSelectedId;
    } catch (error) {
      setChatError(`Failed loading sessions: ${error.message}`);
      return null;
    }
  }

  async function loadSessionMessages(sessionId) {
    setChatLoading(true);
    setChatError("");
    try {
      const rows = await getAgentSessionMessages(agentName, sessionId, 250);
      setMessages(rows);
    } catch (error) {
      setMessages([]);
      setChatError(`Failed loading messages: ${error.message}`);
    } finally {
      setChatLoading(false);
    }
  }

  async function loadSessionArchives() {
    setSessionArchiveLoading(true);
    try {
      const rows = await listArchivedAgentSessions(agentName, 100);
      setSessionArchives(rows || []);
    } catch (error) {
      setChatError(`Failed loading deleted sessions: ${error.message}`);
    } finally {
      setSessionArchiveLoading(false);
    }
  }

  async function handleSaveSettings() {
    setSaving(true);
    setSettingsMessage("");
    try {
      const payload = {
        ...form,
        workspace_paths: normalizeWorkspacePaths(form.workspace_paths_text),
      };
      delete payload.workspace_paths_text;
      await updateAgent(agentName, payload);
      await loadAgent();
      await loadArchives();
      setSettingsMessage("Agent updated successfully.");
    } catch (error) {
      setSettingsMessage(`Error: ${error.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleSyncWorkspace() {
    setSyncingWorkspace(true);
    setArchiveMessage("");
    try {
      const result = await syncWorkspaceResources(normalizeWorkspacePaths(form.workspace_paths_text));
      setArchiveMessage(`Workspace sync updated ${result.items?.length || 0} root(s).`);
      await loadArchives();
    } catch (error) {
      setArchiveMessage(`Workspace sync failed: ${error.message}`);
    } finally {
      setSyncingWorkspace(false);
    }
  }

  async function handleRestoreArchive(entry) {
    if (!entry?.id) return;
    if (!window.confirm(`Restore ${entry.display_path} from archive #${entry.id}?`)) return;
    setArchiveMessage("");
    try {
      await restoreWorkspaceArchive(entry.id, agentName);
      setArchiveMessage(`Restored ${entry.display_path} from archive #${entry.id}.`);
      await loadArchives();
    } catch (error) {
      setArchiveMessage(`Restore failed: ${error.message}`);
    }
  }

  async function handlePreviewVoice() {
    setVoicePreview({ loading: true, error: "", audioB64: "" });
    try {
      const response = await previewAgentVoice(agentName, form.preview_text, form.default_language || "en");
      setVoicePreview({ loading: false, error: "", audioB64: response.audio_b64_wav || "" });
    } catch (error) {
      setVoicePreview({ loading: false, error: error.message, audioB64: "" });
    }
  }

  const selectedTtsModel = useMemo(
    () =>
      ttsModels.find(
        (model) => model.engine === form.tts_engine && model.model_id === form.tts_model_id,
      ) || null,
    [ttsModels, form.tts_engine, form.tts_model_id],
  );

  const languageSupported = useMemo(() => {
    if (!selectedTtsModel) return true;
    const supported = new Set(selectedTtsModel.supports_languages || []);
    return supported.has(form.default_language || "en");
  }, [selectedTtsModel, form.default_language]);
  const showVoiceSettings = Boolean(form.speech_enabled);
  const showWorkspaceSettings = Boolean(form.workspace_enabled);

  async function handleCreateSession() {
    try {
      const created = await createAgentSession(agentName);
      setActiveTab("chat");
      await loadSessions(created.id);
    } catch (error) {
      setChatError(`Failed to create session: ${error.message}`);
    }
  }

  async function handleRenameSession() {
    if (!selectedSession) return;
    const proposedTitle = window.prompt("Session title", selectedSession.title || "");
    if (proposedTitle === null) return;
    try {
      await renameAgentSession(agentName, selectedSession.id, proposedTitle);
      await loadSessions(selectedSession.id);
    } catch (error) {
      setChatError(`Failed renaming session: ${error.message}`);
    }
  }

  async function handleClearSession() {
    if (!selectedSession) return;
    if (!window.confirm("Clear this session context? This keeps the session, but removes all messages.")) return;
    try {
      await clearAgentSession(agentName, selectedSession.id);
      await loadSessions(selectedSession.id);
      await loadSessionMessages(selectedSession.id);
    } catch (error) {
      setChatError(`Failed clearing session: ${error.message}`);
    }
  }

  async function handleDeleteSession() {
    if (!selectedSession) return;
    if (!window.confirm("Delete this session? It will stay in the archive for 30 days and can be restored.")) return;
    setChatError("");
    try {
      await archiveAgentSession(agentName, selectedSession.id);
      await loadSessionArchives();
      const nextSessionId = await loadSessions(null);
      if (nextSessionId) {
        await loadSessionMessages(nextSessionId);
      } else {
        setMessages([]);
      }
    } catch (error) {
      setChatError(`Failed deleting session: ${error.message}`);
    }
  }

  async function handleDeleteAllSessions() {
    if (!sessions.length) return;
    if (!window.confirm("Delete all sessions for this agent? They will stay in the archive for 30 days and can be restored.")) return;
    setChatError("");
    try {
      await archiveAllAgentSessions(agentName);
      await loadSessionArchives();
      const nextSessionId = await loadSessions(null);
      if (nextSessionId) {
        await loadSessionMessages(nextSessionId);
      } else {
        setMessages([]);
      }
    } catch (error) {
      setChatError(`Failed deleting sessions: ${error.message}`);
    }
  }

  async function handleRestoreSession(archive) {
    if (!archive?.id) return;
    setChatError("");
    try {
      const restored = await restoreAgentSessionArchive(agentName, archive.id);
      await loadSessionArchives();
      await loadSessions(restored.id);
      await loadSessionMessages(restored.id);
    } catch (error) {
      setChatError(`Failed restoring session: ${error.message}`);
    }
  }

  async function handleSendMessage(event) {
    event.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed || !selectedSessionId || chatSending) return;

    const startedAt = Date.now();
    const timestamp = new Date(startedAt).toISOString();
    const localUserId = `local-user-${startedAt}`;
    const localAssistantId = `local-assistant-${startedAt}`;

    setChatInput("");
    setChatSending(true);
    setChatError("");
    setChatNotice("");
    setChatRequestStartedAt(startedAt);
    setMessages((prev) => [
      ...prev,
      { id: localUserId, role: "user", content: trimmed, timestamp },
      { id: localAssistantId, role: "assistant", content: "Thinking...", timestamp, isPending: true },
    ]);

    try {
      const result = await chatWithAgent(agentName, trimmed, "auto", selectedSessionId);
      const responseText = String(result.response || "No response received.");
      const warnings = Array.isArray(result.warnings)
        ? result.warnings.map((item) => String(item || "").trim()).filter(Boolean)
        : [];

      setMessages((prev) =>
        prev.map((entry) =>
          entry.id === localAssistantId
            ? { ...entry, content: responseText, isPending: false }
            : entry,
        ),
      );
      if (warnings.length) {
        setChatNotice(warnings.join(" "));
      }
      const activeSessionId = result.session_id || selectedSessionId;
      try {
        await loadSessions(activeSessionId);
        await loadSessionMessages(activeSessionId);
      } catch (refreshError) {
        const refreshMessage = `Reply received, but session refresh failed: ${refreshError.message}`;
        setChatNotice((prev) => (prev ? `${prev} ${refreshMessage}` : refreshMessage));
      }
    } catch (error) {
      setMessages((prev) => prev.filter((entry) => entry.id !== localUserId && entry.id !== localAssistantId));
      setChatInput(trimmed);
      setChatError(`Chat failed: ${error.message}`);
    } finally {
      setChatSending(false);
      setChatRequestStartedAt(null);
    }
  }

  if (!agent) {
    return (
      <div style={{ display: 'grid', gap: 14 }}>
        {[260, 180, 140].map((w, i) => (
          <div key={i} className="glass-card">
            <div className="widget-skeleton">
              <span className="widget-skeleton-line" style={{ width: '30%' }} />
              <span className="widget-skeleton-line" style={{ width: `${w / 3}%` }} />
              <span className="widget-skeleton-line" style={{ width: '55%' }} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div>
      <header className="page-header">
        <button className="btn btn-ghost" onClick={onBack} style={{ marginBottom: 16 }}>
          Back to Agents
        </button>
        <h1>{agentName}</h1>
        <p>Use chat sessions to preserve context per thread, clear context when you want a clean slate, or restore deleted sessions from the 30-day archive.</p>
      </header>

      <div className="agent-config-tabs">
        <button
          type="button"
          className={`btn ${activeTab === "chat" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setActiveTab("chat")}
        >
          Chat
        </button>
        <button
          type="button"
          className={`btn ${activeTab === "settings" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setActiveTab("settings")}
        >
          Settings
        </button>
      </div>

      {activeTab === "chat" ? (
        <div className="chat-layout">
          <section className="glass-card chat-sessions-panel">
            <div className="agent-card-header">
              <h3>Sessions</h3>
              <button className="btn btn-ghost" onClick={handleCreateSession}>
                New session
              </button>
            </div>
            <div className="chat-session-list">
              {sessions.map((session) => (
                <button
                  key={session.id}
                  className={`chat-session-item ${session.id === selectedSessionId ? "active" : ""}`}
                  onClick={() => setSelectedSessionId(session.id)}
                >
                  <strong>{session.title || "New chat"}</strong>
                  <span>{formatSessionTime(session.last_message_at || session.updated_at)}</span>
                </button>
              ))}
            </div>
            <div className="action-row" style={{ marginTop: 12 }}>
              <button className="btn btn-ghost" onClick={handleRenameSession} disabled={!selectedSession}>
                Rename
              </button>
              <button className="btn btn-danger" onClick={handleClearSession} disabled={!selectedSession}>
                Clear context
              </button>
              <button className="btn btn-danger" onClick={handleDeleteSession} disabled={!selectedSession}>
                Delete session
              </button>
              <button className="btn btn-danger" onClick={handleDeleteAllSessions} disabled={!sessions.length}>
                Delete all
              </button>
            </div>
            <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
              <div className="agent-card-header" style={{ marginBottom: 0 }}>
                <h3 style={{ margin: 0 }}>Deleted Sessions</h3>
                <span className="meta-tag">{sessionArchives.length} kept for 30 days</span>
              </div>
              {sessionArchiveLoading ? (
                <p style={{ color: "var(--text-secondary)", margin: 0 }}>Loading deleted sessions...</p>
              ) : sessionArchives.length === 0 ? (
                <p style={{ color: "var(--text-secondary)", margin: 0 }}>
                  Deleted sessions will appear here for 30 days so you can restore them if needed.
                </p>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {sessionArchives.map((archive) => (
                    <div
                      key={archive.id}
                      style={{
                        border: "1px solid var(--card-border)",
                        borderRadius: "var(--radius-md)",
                        padding: 10,
                        display: "grid",
                        gap: 6,
                        background: "rgba(255,255,255,0.02)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                        <strong>{archive.title || "New chat"}</strong>
                        <span className="meta-tag">{archive.message_count} messages</span>
                      </div>
                      <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                        Deleted {formatArchiveTime(archive.created_at)}. Restore until {formatArchiveTime(archive.expires_at)}.
                      </span>
                      <div className="action-row" style={{ marginTop: 0 }}>
                        <button className="btn btn-ghost" type="button" onClick={() => handleRestoreSession(archive)}>
                          Restore
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="glass-card chat-thread-panel">
            <div className="agent-card-header">
              <h3>{selectedSession?.title || "Session"}</h3>
              <span className="meta-tag">{messages.length} messages</span>
            </div>

            <div className="chat-thread">
              {chatLoading ? (
                <div className="empty-state">
                  <p>Loading messages...</p>
                </div>
              ) : messages.length === 0 ? (
                <div className="empty-state">
                  <p>Start the conversation. Session title updates from your first 1-3 prompts.</p>
                </div>
              ) : (
                messages.map((entry) => (
                  <article
                    key={entry.id}
                    className={`chat-message ${entry.role === "user" ? "chat-message-user" : "chat-message-assistant"} ${entry.isPending ? "chat-message-pending" : ""}`}
                  >
                    <header>
                      <strong>{entry.role === "user" ? "You" : agentName}</strong>
                      <time>{formatMessageTime(entry.timestamp)}</time>
                    </header>
                    <p>{entry.content}</p>
                  </article>
                ))
              )}
            </div>

            <form className="chat-composer" onSubmit={handleSendMessage}>
              <textarea
                rows={4}
                placeholder={`Message ${agentName}...`}
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                disabled={!selectedSessionId || chatSending}
              />
              <div className="action-row">
                <button className="btn btn-primary" type="submit" disabled={!selectedSessionId || chatSending}>
                  {chatSending ? "Sending..." : "Send"}
                </button>
              </div>
            </form>
            {chatSending && (
              <div
                style={{
                  marginTop: 12,
                  padding: "12px 14px",
                  borderRadius: 10,
                  border: "1px solid rgba(56,189,248,0.35)",
                  background: "rgba(56,189,248,0.08)",
                  display: "grid",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                  <strong>Thinking...</strong>
                  <span className="meta-tag">{chatElapsedSeconds}s elapsed</span>
                </div>
                <details>
                  <summary style={{ cursor: "pointer" }}>View request status</summary>
                  <div style={{ marginTop: 8, display: "grid", gap: 6, color: "var(--text-secondary)", fontSize: 13 }}>
                    <span>Session #{selectedSessionId}</span>
                    <span>Status: waiting for backend reply.</span>
                    <span>Note: internal reasoning is not shown here; this panel only shows request progress.</span>
                    {form.workspace_enabled && <span>Workspace-enabled agents may take longer while reading files.</span>}
                  </div>
                </details>
              </div>
            )}
            {chatNotice && !chatError && (
              <div
                style={{
                  marginTop: 12,
                  padding: "10px 14px",
                  borderRadius: 10,
                  background: "rgba(59,130,246,0.10)",
                  border: "1px solid rgba(59,130,246,0.25)",
                }}
              >
                {chatNotice}
              </div>
            )}
            {chatError && (
              <div className="token-banner-error" style={{ marginTop: 12 }}>
                {chatError}
              </div>
            )}
          </section>
        </div>
      ) : (
        <div className="glass-card" style={{ maxWidth: 760 }}>
          {settingsMessage && (
            <div
              style={{
                marginBottom: 16,
                padding: "10px 16px",
                borderRadius: 8,
                background: settingsMessage.startsWith("Error:")
                  ? "rgba(239,68,68,0.1)"
                  : "rgba(34,197,94,0.1)",
              }}
            >
              {settingsMessage}
            </div>
          )}
          {archiveMessage && (
            <div
              style={{
                marginBottom: 16,
                padding: "10px 16px",
                borderRadius: 8,
                background: archiveMessage.includes("failed") || archiveMessage.includes("Error:")
                  ? "rgba(239,68,68,0.1)"
                  : "rgba(59,130,246,0.1)",
              }}
            >
              {archiveMessage}
            </div>
          )}

          <div className="form-group">
            <label>Description</label>
            <input
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </div>

          <div className="form-group">
            <label>System Prompt</label>
            <textarea
              rows={6}
              value={form.system_prompt}
              onChange={(event) => setForm({ ...form, system_prompt: event.target.value })}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="form-group">
              <label>Provider</label>
              <select value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value })}>
                {providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>
                    {provider.name.toUpperCase()} {provider.available ? "AVAILABLE" : "UNAVAILABLE"}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Model</label>
              <input
                value={form.model}
                onChange={(event) => setForm({ ...form, model: event.target.value })}
                placeholder="e.g. openrouter/free"
              />
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="form-group">
              <label>Fallback Provider</label>
              <select
                value={form.fallback_provider}
                onChange={(event) => setForm({ ...form, fallback_provider: event.target.value })}
              >
                <option value="">None</option>
                {providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>
                    {provider.name.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Fallback Model</label>
              <input
                value={form.fallback_model}
                onChange={(event) => setForm({ ...form, fallback_model: event.target.value })}
                placeholder="Optional"
              />
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="form-group">
              <label>Discord Channel</label>
              <input
                value={form.discord_channel}
                onChange={(event) => setForm({ ...form, discord_channel: event.target.value })}
                placeholder="e.g. prayer-tracker"
              />
            </div>
            <div className="form-group">
              <label>Schedule (cron: min hour dow)</label>
              <input
                value={form.cadence}
                onChange={(event) => setForm({ ...form, cadence: event.target.value })}
                placeholder="e.g. 0 8 *"
              />
            </div>
          </div>

          <div className="form-group">
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={Boolean(form.enabled)}
                onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
                style={{ width: "auto" }}
              />
              Enabled
            </label>
          </div>

          <hr style={{ margin: "20px 0", borderColor: "rgba(148,163,184,0.25)" }} />

          <h3 style={{ marginTop: 0 }}>Voice</h3>
          <div className="form-group">
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={Boolean(form.speech_enabled)}
                onChange={(event) => setForm({ ...form, speech_enabled: event.target.checked })}
                style={{ width: "auto" }}
              />
              Speech enabled
            </label>
          </div>

          {showVoiceSettings ? (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div className="form-group">
                  <label>TTS Engine</label>
                  <select
                    value={form.tts_engine || "chatterbox_turbo"}
                    onChange={(event) => {
                      const nextEngine = event.target.value;
                      const options = ttsModels.filter((model) => model.engine === nextEngine);
                      setForm({
                        ...form,
                        tts_engine: nextEngine,
                        tts_model_id: options[0]?.model_id || "",
                      });
                    }}
                  >
                    {Array.from(new Set(ttsModels.map((model) => model.engine))).map((engine) => (
                      <option key={engine} value={engine}>
                        {engine}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>TTS Model</label>
                  <select
                    value={form.tts_model_id || ""}
                    onChange={(event) => setForm({ ...form, tts_model_id: event.target.value })}
                  >
                    {ttsModels
                      .filter((model) => model.engine === form.tts_engine)
                      .map((model) => (
                        <option key={`${model.engine}:${model.model_id}`} value={model.model_id}>
                          {model.display_name}
                        </option>
                      ))}
                  </select>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <div className="form-group">
                  <label>Voice ID / Speaker</label>
                  <input
                    value={form.voice_id || ""}
                    onChange={(event) => setForm({ ...form, voice_id: event.target.value })}
                    placeholder="Optional speaker/voice key"
                  />
                </div>
                <div className="form-group">
                  <label>Default Language</label>
                  <select
                    value={form.default_language || "en"}
                    onChange={(event) => setForm({ ...form, default_language: event.target.value })}
                  >
                    <option value="en">English</option>
                    <option value="fr">French</option>
                    <option value="ar">Arabic</option>
                  </select>
                </div>
              </div>

              {!languageSupported && (
                <div className="token-banner-error" style={{ marginBottom: 12 }}>
                  Selected TTS model does not support {form.default_language?.toUpperCase()}. Choose a compatible model.
                </div>
              )}

              <div className="form-group">
                <label>Voice Instructions</label>
                <textarea
                  rows={3}
                  value={form.voice_instructions || ""}
                  onChange={(event) => setForm({ ...form, voice_instructions: event.target.value })}
                  placeholder="Tone and style guidance for this agent voice"
                />
              </div>

              <details style={{ marginBottom: 14 }}>
                <summary style={{ cursor: "pointer" }}>Advanced voice controls</summary>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, marginTop: 12 }}>
                  <div className="form-group">
                    <label>Speed</label>
                    <input
                      type="number"
                      step="0.1"
                      value={form.voice_params_json?.speed ?? 1.0}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          voice_params_json: { ...(form.voice_params_json || {}), speed: Number(event.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Stability</label>
                    <input
                      type="number"
                      step="0.1"
                      value={form.voice_params_json?.stability ?? 0.7}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          voice_params_json: { ...(form.voice_params_json || {}), stability: Number(event.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Temperature</label>
                    <input
                      type="number"
                      step="0.1"
                      value={form.voice_params_json?.temperature ?? 0.6}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          voice_params_json: { ...(form.voice_params_json || {}), temperature: Number(event.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Emotion Intensity</label>
                    <input
                      type="number"
                      step="0.1"
                      value={form.voice_params_json?.emotion_intensity ?? 0.6}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          voice_params_json: {
                            ...(form.voice_params_json || {}),
                            emotion_intensity: Number(event.target.value),
                          },
                        })
                      }
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Reference Audio Path (Phase 2)</label>
                  <input
                    value={form.reference_audio_path || ""}
                    onChange={(event) => setForm({ ...form, reference_audio_path: event.target.value })}
                    placeholder="/app/data/voices/ref.wav"
                  />
                </div>
                <div className="form-group">
                  <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={Boolean(form.voice_visible_in_runtime_picker)}
                      onChange={(event) => setForm({ ...form, voice_visible_in_runtime_picker: event.target.checked })}
                      style={{ width: "auto" }}
                    />
                    Visible in runtime voice picker
                  </label>
                </div>
              </details>

              <div className="form-group">
                <label>Preview text</label>
                <textarea
                  rows={2}
                  value={form.preview_text || ""}
                  onChange={(event) => setForm({ ...form, preview_text: event.target.value })}
                />
              </div>

              <div className="action-row" style={{ marginBottom: 16 }}>
                <button
                  className="btn btn-ghost"
                  onClick={handlePreviewVoice}
                  disabled={voicePreview.loading || !languageSupported}
                  type="button"
                >
                  {voicePreview.loading ? "Generating preview..." : "Preview Voice"}
                </button>
              </div>
              {voicePreview.error && (
                <div className="token-banner-error" style={{ marginBottom: 12 }}>
                  {voicePreview.error}
                </div>
              )}
              {voicePreview.audioB64 && (
                <audio
                  controls
                  src={`data:audio/wav;base64,${voicePreview.audioB64}`}
                  style={{ width: "100%", marginBottom: 16 }}
                />
              )}
            </>
          ) : null}

          <hr style={{ margin: "20px 0", borderColor: "rgba(148,163,184,0.25)" }} />

          <h3 style={{ marginTop: 0 }}>Workspace</h3>
          <div className="form-group">
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={Boolean(form.workspace_enabled)}
                onChange={(event) => setForm({ ...form, workspace_enabled: event.target.checked })}
                style={{ width: "auto" }}
              />
              Enable OpenViking repo retrieval and file edits
            </label>
          </div>
          {showWorkspaceSettings ? (
            <>
              <div className="form-group">
                <label>Workspace Paths</label>
                <textarea
                  rows={4}
                  value={form.workspace_paths_text || ""}
                  onChange={(event) => setForm({ ...form, workspace_paths_text: event.target.value })}
                  placeholder="/workspace"
                />
                <small>One absolute or repo-relative path per line. Deletes still require approval and every change is archived.</small>
              </div>
              <div className="form-group">
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "not-allowed", opacity: 0.85 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(form.workspace_delete_requires_approval)}
                    disabled
                    style={{ width: "auto" }}
                  />
                  File deletions require approval
                </label>
              </div>
              <div className="action-row" style={{ marginBottom: 16 }}>
                <button
                  className="btn btn-ghost"
                  onClick={handleSyncWorkspace}
                  disabled={syncingWorkspace}
                  type="button"
                >
                  {syncingWorkspace ? "Syncing..." : "Sync Workspace Context"}
                </button>
              </div>

              <div className="agent-card-header" style={{ marginBottom: 12 }}>
                <h3 style={{ margin: 0 }}>Archive History</h3>
                <span className="meta-tag">{archives.length} entries</span>
              </div>
              {archiveLoading ? (
                <p>Loading archive entries...</p>
              ) : archives.length === 0 ? (
                <p>No archived workspace changes yet.</p>
              ) : (
                <div style={{ display: "grid", gap: 12, marginBottom: 20 }}>
                  {archives.map((entry) => (
                    <div
                      key={entry.id}
                      style={{
                        border: "1px solid rgba(148,163,184,0.18)",
                        borderRadius: 12,
                        padding: 14,
                        display: "grid",
                        gap: 8,
                      }}
                    >
                      <div className="agent-card-header">
                        <div>
                          <strong>{entry.display_path}</strong>
                          <div style={{ fontSize: 12, opacity: 0.75 }}>
                            {entry.operation_type} by {entry.agent_name}
                          </div>
                        </div>
                        <span className="meta-tag">{entry.status}</span>
                      </div>
                      <div style={{ fontSize: 13, opacity: 0.8 }}>
                        Archive #{entry.id} • {formatArchiveTime(entry.resolved_at || entry.created_at)}
                      </div>
                      <div className="action-row">
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => handleRestoreArchive(entry)}
                          disabled={!entry.archive_path}
                        >
                          Restore
                        </button>
                        {entry.pending_action_id ? (
                          <span className="meta-tag">Approval #{entry.pending_action_id}</span>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : null}

          <div className="action-row">
            <button className="btn btn-primary" onClick={handleSaveSettings} disabled={saving}>
              {saving ? "Saving..." : "Save Changes"}
            </button>
            <button className="btn btn-ghost" onClick={onBack}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
