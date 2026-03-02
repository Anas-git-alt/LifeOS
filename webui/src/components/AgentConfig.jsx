import { useEffect, useMemo, useState } from "react";
import {
  chatWithAgent,
  clearAgentSession,
  createAgentSession,
  getAgent,
  getAgentSessionMessages,
  getProviders,
  listAgentSessions,
  renameAgentSession,
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

export default function AgentConfig({ agentName, onBack }) {
  const [agent, setAgent] = useState(null);
  const [providers, setProviders] = useState([]);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [activeTab, setActiveTab] = useState("chat");

  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatSending, setChatSending] = useState(false);
  const [chatError, setChatError] = useState("");

  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) || null,
    [sessions, selectedSessionId],
  );

  useEffect(() => {
    if (!agentName) return;
    setAgent(null);
    setSettingsMessage("");
    setChatError("");
    setSessions([]);
    setSelectedSessionId(null);
    setMessages([]);
    setChatInput("");
    loadAgent();
    loadProviders();
    loadSessions(null);
  }, [agentName]);

  useEffect(() => {
    if (!agentName || !selectedSessionId) return;
    loadSessionMessages(selectedSessionId);
  }, [agentName, selectedSessionId]);

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
      });
    } catch (error) {
      setSettingsMessage(`Error: ${error.message}`);
    }
  }

  async function loadProviders() {
    try {
      setProviders(await getProviders());
    } catch (error) {
      // Keep agent settings editable even if providers endpoint fails.
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

  async function handleSaveSettings() {
    setSaving(true);
    setSettingsMessage("");
    try {
      await updateAgent(agentName, form);
      setSettingsMessage("Agent updated successfully.");
    } catch (error) {
      setSettingsMessage(`Error: ${error.message}`);
    } finally {
      setSaving(false);
    }
  }

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

  async function handleSendMessage(event) {
    event.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed || !selectedSessionId || chatSending) return;

    setChatInput("");
    setChatSending(true);
    setChatError("");

    try {
      const result = await chatWithAgent(agentName, trimmed, "auto", selectedSessionId);
      const activeSessionId = result.session_id || selectedSessionId;
      await loadSessions(activeSessionId);
      await loadSessionMessages(activeSessionId);
    } catch (error) {
      setChatError(`Chat failed: ${error.message}`);
    } finally {
      setChatSending(false);
    }
  }

  if (!agent) {
    return (
      <div className="empty-state">
        <p>Loading...</p>
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
        <p>Use chat sessions to preserve context per thread, or clear context without losing the session.</p>
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
                    className={`chat-message ${entry.role === "user" ? "chat-message-user" : "chat-message-assistant"}`}
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
                placeholder="e.g. openrouter/auto"
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
