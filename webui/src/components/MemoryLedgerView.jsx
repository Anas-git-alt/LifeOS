import { useEffect, useState } from "react";
import {
  archivePrivateMemoryEvent,
  getPrivateMemoryEvents,
  restorePrivateMemoryEvent,
} from "../api";

const STATUS_OPTIONS = ["active", "archived", "deleted"];

export default function MemoryLedgerView() {
  const [status, setStatus] = useState("active");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setRows(await getPrivateMemoryEvents({ status, limit: 100 }));
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [status]);

  async function setArchived(eventId, archived) {
    setMessage("");
    setError("");
    try {
      if (archived) {
        await archivePrivateMemoryEvent(eventId);
        setMessage(`Archived memory #${eventId}.`);
      } else {
        await restorePrivateMemoryEvent(eventId);
        setMessage(`Restored memory #${eventId}.`);
      }
      await load();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  return (
    <section>
      <div className="page-header">
        <h1>Memory Ledger</h1>
        <p>Private user-authored memories with source, audit state, and archive restore.</p>
      </div>

      <div className="glass-card" style={{ marginBottom: 16 }}>
        <div className="action-row">
          <label htmlFor="memory-status">Status</label>
          <select id="memory-status" value={status} onChange={(event) => setStatus(event.target.value)}>
            {STATUS_OPTIONS.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
          <button className="btn btn-ghost" type="button" onClick={load}>Refresh</button>
        </div>
      </div>

      {message && <div className="glass-card status-message-success" style={{ marginBottom: 16 }}>{message}</div>}
      {error && <div className="glass-card status-message-error" style={{ marginBottom: 16 }}>{error}</div>}

      {loading ? (
        <div className="glass-card">Loading memories...</div>
      ) : rows.length === 0 ? (
        <div className="glass-card empty-state">No {status} memories.</div>
      ) : (
        <div className="grid">
          {rows.map((row) => (
            <article key={row.id} className="glass-card">
              <div className="agent-card-header" style={{ alignItems: "flex-start" }}>
                <div>
                  <h3 style={{ marginBottom: 6 }}>#{row.id} {row.title}</h3>
                  <div className="agent-meta">
                    <span className="meta-tag">{row.status}</span>
                    <span className="meta-tag">{row.scope}</span>
                    <span className="meta-tag">{row.domain || "general"}/{row.kind || row.event_type}</span>
                    <span className="meta-tag">{row.confidence || "unknown"}</span>
                  </div>
                </div>
                {row.status === "active" ? (
                  <button className="btn btn-ghost" onClick={() => setArchived(row.id, true)}>Archive</button>
                ) : row.status === "archived" ? (
                  <button className="btn btn-primary" onClick={() => setArchived(row.id, false)}>Restore</button>
                ) : null}
              </div>
              <p style={{ marginTop: 10 }}>{row.summary || row.raw_text}</p>
              <p className="job-card-meta">Source: {row.source} · agent {row.source_agent || "n/a"} · session {row.source_session_id || "n/a"}</p>
              <p className="job-card-meta">Created: {new Date(row.created_at).toLocaleString()}</p>
              <p className="job-card-meta">Why saved: {row.why_saved || "Private memory"}</p>
              <details style={{ marginTop: 10 }}>
                <summary>Source message</summary>
                <pre style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>{row.source_message || row.raw_text}</pre>
              </details>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
