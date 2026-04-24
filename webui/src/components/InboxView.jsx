import { useEffect, useState } from "react";
import {
  captureIntake,
  getAgentSessionMessages,
  getIntakeInbox,
  promoteIntakeEntry,
  updateIntakeEntry,
} from "../api";

const STATUS_OPTIONS = ["clarifying", "ready", "parked", "archived"];

export default function InboxView() {
  const [entries, setEntries] = useState([]);
  const [selectedEntryId, setSelectedEntryId] = useState(null);
  const [conversation, setConversation] = useState([]);
  const [draft, setDraft] = useState("");
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [promotingId, setPromotingId] = useState(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const selected = entries.find((entry) => entry.id === selectedEntryId);
    const nextSessionId = selected?.source_session_id || null;
    setActiveSessionId(nextSessionId);
    if (!nextSessionId) {
      setConversation([]);
      return;
    }
    loadConversation(nextSessionId);
  }, [entries, selectedEntryId]);

  async function load(preferredId = null) {
    try {
      const rows = await getIntakeInbox({ limit: 50 });
      setEntries(rows);
      setError("");
      const targetId = preferredId || selectedEntryId;
      const targetExists = targetId && rows.some((entry) => entry.id === targetId);
      if (targetExists) {
        setSelectedEntryId(targetId);
      } else if (rows[0]) {
        setSelectedEntryId(rows[0].id);
      } else {
        setSelectedEntryId(null);
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadConversation(sessionId) {
    try {
      setChatLoading(true);
      const rows = await getAgentSessionMessages("intake-inbox", sessionId, 30);
      setConversation(rows);
      setError("");
    } catch (err) {
      setConversation([]);
      setError(err.message);
    } finally {
      setChatLoading(false);
    }
  }

  async function handleCapture(newSession) {
    const message = draft.trim();
    if (!message) return;
    setLoading(true);
    setSuccess("");
    try {
      const result = await captureIntake(
        message,
        newSession ? null : activeSessionId,
        newSession || !activeSessionId,
        newSession ? "webui_capture" : "webui_capture_followup",
      );
      setDraft("");
      const created = result.auto_promoted_count || result.life_items?.length || 0;
      const proposals = result.wiki_proposals?.length || 0;
      setSuccess(
        newSession
          ? `Captured. Auto-created ${created} life item(s), ${proposals} wiki proposal(s).`
          : `Follow-up saved. Auto-created ${created} life item(s), ${proposals} wiki proposal(s).`,
      );
      if (result.session_id) {
        setActiveSessionId(result.session_id);
        await loadConversation(result.session_id);
      }
      await load(result.entry?.id || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleStatusChange(entryId, status) {
    try {
      await updateIntakeEntry(entryId, { status });
      setSuccess(`Inbox item marked ${status}.`);
      await load(entryId);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handlePromote(entryId) {
    setPromotingId(entryId);
    try {
      const result = await promoteIntakeEntry(entryId, {});
      setSuccess(`Promoted to life item #${result.life_item.id}: ${result.life_item.title}`);
      await load(entryId);
    } catch (err) {
      setError(err.message);
    } finally {
      setPromotingId(null);
    }
  }

  const selectedEntry = entries.find((entry) => entry.id === selectedEntryId) || null;
  const intakeSummary = entries.reduce((summary, entry) => {
    summary[entry.status] = (summary[entry.status] || 0) + 1;
    return summary;
  }, {});

  return (
    <div>
      <header className="page-header">
        <h1>Inbox</h1>
        <p>Capture messy thoughts, let the agent clarify, then promote the good ones into your life system.</p>
      </header>

      {error && <div className="glass-card status-message-error" style={{ marginBottom: 16 }}>{error}</div>}
      {success && <div className="glass-card status-message-success" style={{ marginBottom: 16 }}>{success}</div>}

      <div className="glass-card" style={{ marginBottom: 20 }}>
        <div className="grid grid-4" style={{ marginBottom: 16 }}>
          <div>
            <div className="stat-value">{entries.length}</div>
            <div className="stat-label">Inbox Items</div>
          </div>
          <div>
            <div className="stat-value">{intakeSummary.ready || 0}</div>
            <div className="stat-label">Ready</div>
          </div>
          <div>
            <div className="stat-value">{intakeSummary.clarifying || 0}</div>
            <div className="stat-label">Clarifying</div>
          </div>
          <div>
            <div className="stat-value">{intakeSummary.parked || 0}</div>
            <div className="stat-label">Parked</div>
          </div>
        </div>

        <div className="form-group" style={{ marginBottom: 10 }}>
          <label>Quick Capture</label>
          <textarea
            rows={4}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Dump an idea, promise, friction point, goal, or life upgrade you want help structuring..."
          />
        </div>
        <div className="action-row">
          <button className="btn btn-primary" disabled={loading || !draft.trim()} onClick={() => handleCapture(true)}>
            {loading ? "Capturing..." : "Capture New"}
          </button>
          <button className="btn btn-ghost" disabled={loading || !draft.trim() || !activeSessionId} onClick={() => handleCapture(false)}>
            Continue Current
          </button>
          {activeSessionId && (
            <span className="meta-tag">Active session #{activeSessionId}</span>
          )}
        </div>
      </div>

      <div className="chat-layout">
        <div className="glass-card chat-sessions-panel">
          <div className="panel-card-head">
            <h2>Inbox Queue</h2>
            <span>{entries.length} items</span>
          </div>
          <div className="chat-session-list">
            {entries.length === 0 ? (
              <div className="empty-state" style={{ padding: "16px 10px" }}>No inbox items yet.</div>
            ) : (
              entries.map((entry) => (
                <button
                  key={entry.id}
                  className={`chat-session-item ${selectedEntryId === entry.id ? "active" : ""}`}
                  onClick={() => setSelectedEntryId(entry.id)}
                >
                  <strong>#{entry.id} {entry.title || "Untitled"}</strong>
                  <span>{entry.status} · {entry.domain}/{entry.kind}</span>
                  <span>{new Date(entry.updated_at).toLocaleString()}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {!selectedEntry ? (
            <div className="glass-card empty-state">Select an inbox item to inspect details.</div>
          ) : (
            <>
              <div className="glass-card">
                <div className="agent-card-header" style={{ alignItems: "flex-start" }}>
                  <div>
                    <h3 style={{ marginBottom: 6 }}>#{selectedEntry.id} {selectedEntry.title || "Untitled"}</h3>
                    <div className="agent-meta">
                      <span className="meta-tag">{selectedEntry.status}</span>
                      <span className="meta-tag">{selectedEntry.domain}</span>
                      <span className="meta-tag">{selectedEntry.kind}</span>
                      {selectedEntry.linked_life_item_id && (
                        <span className="meta-tag">Life item #{selectedEntry.linked_life_item_id}</span>
                      )}
                    </div>
                  </div>
                  <div className="action-row" style={{ marginTop: 0, justifyContent: "flex-end" }}>
                    {STATUS_OPTIONS.map((status) => (
                      <button
                        key={status}
                        className="btn btn-ghost"
                        disabled={selectedEntry.status === status}
                        onClick={() => handleStatusChange(selectedEntry.id, status)}
                      >
                        {status}
                      </button>
                    ))}
                    <button
                      className="btn btn-primary"
                      disabled={promotingId === selectedEntry.id || Boolean(selectedEntry.linked_life_item_id)}
                      onClick={() => handlePromote(selectedEntry.id)}
                    >
                      {promotingId === selectedEntry.id ? "Promoting..." : selectedEntry.linked_life_item_id ? "Promoted" : "Promote"}
                    </button>
                  </div>
                </div>

                <div style={{ display: "grid", gap: 12, fontSize: 13.5 }}>
                  <div>
                    <strong>Raw capture</strong>
                    <p style={{ marginTop: 6, color: "var(--text-secondary)" }}>{selectedEntry.raw_text}</p>
                  </div>

                  {selectedEntry.summary && (
                    <div>
                      <strong>Current understanding</strong>
                      <p style={{ marginTop: 6, color: "var(--text-secondary)" }}>{selectedEntry.summary}</p>
                    </div>
                  )}

                  {selectedEntry.desired_outcome && (
                    <div>
                      <strong>Desired outcome</strong>
                      <p style={{ marginTop: 6, color: "var(--text-secondary)" }}>{selectedEntry.desired_outcome}</p>
                    </div>
                  )}

                  {selectedEntry.next_action && (
                    <div>
                      <strong>Suggested next action</strong>
                      <p style={{ marginTop: 6, color: "var(--text-secondary)" }}>{selectedEntry.next_action}</p>
                    </div>
                  )}

                  {selectedEntry.promotion_payload?.priority_reason && (
                    <div>
                      <strong>AI priority</strong>
                      <p style={{ marginTop: 6, color: "var(--text-secondary)" }}>
                        {selectedEntry.promotion_payload.priority_score ?? "?"}/100 · {selectedEntry.promotion_payload.priority_reason}
                      </p>
                    </div>
                  )}

                  {(selectedEntry.promotion_payload?.context_links || []).length > 0 && (
                    <div>
                      <strong>Context links</strong>
                      <ul style={{ marginTop: 8, paddingLeft: 18, color: "var(--text-secondary)", display: "grid", gap: 6 }}>
                        {selectedEntry.promotion_payload.context_links.map((link, index) => (
                          <li key={`${selectedEntry.id}-context-${index}`}>
                            {link.title || link.uri || link.path}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {selectedEntry.follow_up_questions?.length > 0 && (
                    <div>
                      <strong>Follow-up questions</strong>
                      <ul style={{ marginTop: 8, paddingLeft: 18, color: "var(--text-secondary)", display: "grid", gap: 6 }}>
                        {selectedEntry.follow_up_questions.map((question, index) => (
                          <li key={`${selectedEntry.id}-question-${index}`}>{question}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>

              <div className="glass-card">
                <div className="panel-card-head">
                  <h2>Intake Conversation</h2>
                  <span>{selectedEntry.source_session_id ? `Session #${selectedEntry.source_session_id}` : "No session"}</span>
                </div>
                {chatLoading ? (
                  <div className="empty-state" style={{ padding: "16px 10px" }}>Loading conversation...</div>
                ) : conversation.length === 0 ? (
                  <div className="empty-state" style={{ padding: "16px 10px" }}>No conversation yet for this entry.</div>
                ) : (
                  <div style={{ display: "grid", gap: 10, maxHeight: "38vh", overflowY: "auto", paddingRight: 4 }}>
                    {conversation.map((message, index) => (
                      <div
                        key={`${message.timestamp || index}-${index}`}
                        style={{
                          border: "1px solid var(--card-border)",
                          borderRadius: 10,
                          padding: "10px 12px",
                          background: message.role === "user" ? "rgba(255,255,255,0.02)" : "rgba(124,58,237,0.08)",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 6 }}>
                          <strong style={{ fontSize: 12, textTransform: "uppercase", color: "var(--text-secondary)" }}>
                            {message.role === "user" ? "You" : "Agent"}
                          </strong>
                          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                            {message.timestamp ? new Date(message.timestamp).toLocaleString() : ""}
                          </span>
                        </div>
                        <div style={{ whiteSpace: "pre-wrap", fontSize: 13.5 }}>{message.content}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
