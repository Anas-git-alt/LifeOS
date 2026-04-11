import { useEffect, useState } from "react";
import { getTodayAgenda } from "../api";

export default function TodayView() {
  const [agenda, setAgenda] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setAgenda(await getTodayAgenda());
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <header className="page-header">
        <h1>Today</h1>
        <p>Prayer-aware and shift-aware focus overview.</p>
      </header>
      {error && <div className="glass-card">{error}</div>}
      {agenda && (
        <>
          <div className="grid grid-4" style={{ marginBottom: 20 }}>
            <div className="glass-card">
              <div className="stat-label">Timezone</div>
              <div>{agenda.timezone}</div>
            </div>
            <div className="glass-card">
              <div className="stat-label">Now</div>
              <div>{new Date(agenda.now).toLocaleString()}</div>
            </div>
            <div className="glass-card">
              <div className="stat-label">Open Domains</div>
              <div>{Object.keys(agenda.domain_summary || {}).length}</div>
            </div>
            <div className="glass-card">
              <div className="stat-label">Inbox Ready</div>
              <div>{agenda.intake_summary?.ready || 0}</div>
            </div>
          </div>
          <div className="grid grid-4">
            <AgendaBlock title="Top Focus" items={agenda.top_focus || []} />
            <AgendaBlock title="Due Today" items={agenda.due_today || []} />
            <AgendaBlock title="Overdue" items={agenda.overdue || []} />
            <InboxBlock title="Inbox Ready" items={agenda.ready_intake || []} summary={agenda.intake_summary || {}} />
          </div>
        </>
      )}
    </div>
  );
}

function AgendaBlock({ title, items }) {
  return (
    <div className="glass-card">
      <h3 style={{ marginBottom: 12 }}>{title}</h3>
      {items.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>None</p>
      ) : (
        <ul style={{ display: "grid", gap: 8 }}>
          {items.map((item) => (
            <li key={item.id} style={{ listStyle: "none" }}>
              #{item.id} {item.title}
              <div className="meta-tag" style={{ marginTop: 4 }}>
                {item.domain} / {item.priority}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function InboxBlock({ title, items, summary }) {
  return (
    <div className="glass-card">
      <h3 style={{ marginBottom: 12 }}>{title}</h3>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        <span className="meta-tag">ready {summary.ready || 0}</span>
        <span className="meta-tag">clarifying {summary.clarifying || 0}</span>
        <span className="meta-tag">parked {summary.parked || 0}</span>
      </div>
      {items.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>Inbox clear enough for today.</p>
      ) : (
        <ul style={{ display: "grid", gap: 8 }}>
          {items.map((item) => (
            <li key={item.id} style={{ listStyle: "none" }}>
              #{item.id} {item.title || item.raw_text}
              <div className="meta-tag" style={{ marginTop: 4 }}>
                {item.status} / {item.domain} / {item.kind}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
