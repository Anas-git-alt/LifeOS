import { useEffect, useState } from "react";
import {
  applyMemoryProposal,
  captureMeetingSummary,
  curateMemoryEvent,
  getMemoryEvents,
  getVaultConflicts,
} from "../api";

const DOMAINS = ["planning", "work", "health", "deen", "family"];

export default function WikiView() {
  const [form, setForm] = useState({ title: "", domain: "planning", summary: "" });
  const [events, setEvents] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [eventRows, proposalRows] = await Promise.all([
        getMemoryEvents({ limit: 30 }),
        getVaultConflicts(),
      ]);
      setEvents(eventRows);
      setProposals(proposalRows);
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const submitMeeting = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const result = await captureMeetingSummary({
        title: form.title || null,
        domain: form.domain || null,
        summary: form.summary,
        source: "webui_meeting",
        source_agent: "wiki-curator",
      });
      setMessage(`Captured event #${result.event.id}; created ${result.proposals.length} wiki proposal(s).`);
      setForm({ title: "", domain: "planning", summary: "" });
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setSaving(false);
    }
  };

  const curateEvent = async (eventId) => {
    setError("");
    setMessage("");
    try {
      const result = await curateMemoryEvent(eventId);
      setMessage(`Curated event #${result.event.id}; ${result.proposals.length} proposal(s) ready.`);
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  };

  const applyProposal = async (proposalId) => {
    setError("");
    setMessage("");
    try {
      await applyMemoryProposal(proposalId, "webui");
      setMessage(`Applied wiki proposal #${proposalId}.`);
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  };

  return (
    <section className="glass-card">
      <div className="page-header">
        <h2>Wiki Context</h2>
        <p>Capture meeting summaries, review proposed Obsidian notes, and keep shared context connected.</p>
      </div>

      <form onSubmit={submitMeeting}>
        <div className="grid grid-2">
          <div className="form-group">
            <label htmlFor="wiki-title">Title</label>
            <input
              id="wiki-title"
              value={form.title}
              onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
              placeholder="Optional meeting title"
            />
          </div>
          <div className="form-group">
            <label htmlFor="wiki-domain">Domain</label>
            <select
              id="wiki-domain"
              value={form.domain}
              onChange={(e) => setForm((prev) => ({ ...prev, domain: e.target.value }))}
            >
              {DOMAINS.map((domain) => (
                <option key={domain} value={domain}>
                  {domain}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="form-group">
          <label htmlFor="wiki-summary">Meeting Summary</label>
          <textarea
            id="wiki-summary"
            rows={8}
            value={form.summary}
            onChange={(e) => setForm((prev) => ({ ...prev, summary: e.target.value }))}
            required
            placeholder="Paste decisions, context, action items, names, links, and anything you want LifeOS to remember."
          />
        </div>
        <div className="action-row">
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? "Capturing..." : "Capture Meeting"}
          </button>
          <button className="btn btn-ghost" type="button" onClick={loadData}>
            Refresh
          </button>
        </div>
      </form>

      {message && <p className="success-text" style={{ marginTop: 12 }}>{message}</p>}
      {error && <p className="error-text" style={{ marginTop: 12 }}>{error}</p>}

      {loading ? (
        <p style={{ marginTop: 16 }}>Loading wiki context...</p>
      ) : (
        <div className="grid grid-2" style={{ marginTop: 18 }}>
          <section>
            <h3>Pending Wiki Proposals</h3>
            {proposals.length === 0 ? (
              <p>No pending proposals.</p>
            ) : (
              <div className="grid">
                {proposals.map((proposal) => (
                  <article key={proposal.id} className="glass-card">
                    <h4>#{proposal.id} {proposal.title}</h4>
                    <p className="job-card-meta">
                      {proposal.domain || "global"} · {proposal.conflict_reason}
                    </p>
                    <p className="job-card-meta">{proposal.target_path}</p>
                    <button className="btn btn-primary" onClick={() => applyProposal(proposal.id)}>
                      Apply
                    </button>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section>
            <h3>Context Events</h3>
            {events.length === 0 ? (
              <p>No context events yet.</p>
            ) : (
              <div className="grid">
                {events.map((event) => (
                  <article key={event.id} className="glass-card">
                    <h4>#{event.id} {event.title || event.event_type}</h4>
                    <p className="job-card-meta">
                      {event.event_type} · {event.domain} · {event.status}
                    </p>
                    <p className="job-card-meta">{(event.summary || event.raw_text || "").slice(0, 180)}</p>
                    {event.status !== "curated" && (
                      <button className="btn btn-ghost" onClick={() => curateEvent(event.id)}>
                        Curate
                      </button>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

