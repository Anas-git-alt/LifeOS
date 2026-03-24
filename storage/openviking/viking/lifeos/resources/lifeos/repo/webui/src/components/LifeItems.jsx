import { useEffect, useState } from "react";
import { checkinLifeItem, createLifeItem, getLifeItems } from "../api";

const domains = ["deen", "family", "work", "health", "planning"];
const kinds = ["task", "goal", "habit"];

export default function LifeItems({ onGoalSelect }) {
  const [items, setItems] = useState([]);
  const [domain, setDomain] = useState("planning");
  const [kind, setKind] = useState("task");
  const [title, setTitle] = useState("");
  const [startDate, setStartDate] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setItems(await getLifeItems({ status: "open" }));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function addItem() {
    if (!title.trim()) return;
    try {
      await createLifeItem({
        domain,
        title: title.trim(),
        kind,
        priority: "medium",
        start_date: startDate || null,
      });
      setTitle("");
      setStartDate("");
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function mark(id, result) {
    try {
      await checkinLifeItem(id, result, "");
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <header className="page-header">
        <h1>Life Items</h1>
        <p>Unified domain tasks, commitments, habits, and goals.</p>
      </header>
      {error && <div className="glass-card" style={{ marginBottom: 12, color: "var(--accent-red)" }}>{error}</div>}
      <div className="glass-card" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
          <select value={domain} onChange={(e) => setDomain(e.target.value)} style={{ width: "auto", minWidth: 100 }}>
            {domains.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: "auto", minWidth: 90 }}>
            {kinds.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="New life item..." style={{ flex: 1, minWidth: 160 }} />
          <button className="btn btn-primary" onClick={addItem}>Add</button>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ margin: 0, fontSize: 12, whiteSpace: "nowrap" }}>Start date:</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            style={{ width: "auto", maxWidth: 170, fontSize: 13 }}
          />
        </div>
      </div>
      <div style={{ display: "grid", gap: 12 }}>
        {items.map((item) => (
          <div key={item.id} className="glass-card">
            <div className="agent-card-header">
              <h3>
                #{item.id} {item.title}
              </h3>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span className="badge badge-active">
                  {item.domain} / {item.kind || "task"}
                </span>
                {item.source_agent && (
                  <span className="meta-tag" style={{ fontSize: 11 }}>🤖 {item.source_agent}</span>
                )}
              </div>
            </div>
            {item.start_date && (
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>
                Started: {item.start_date}
              </div>
            )}
            <div className="action-row">
              <button className="btn btn-success" onClick={() => mark(item.id, "done")}>Done</button>
              <button className="btn btn-danger" onClick={() => mark(item.id, "missed")}>Missed</button>
              {onGoalSelect && (
                <button className="btn btn-ghost" onClick={() => onGoalSelect(item.id)}>
                  📊 Progress
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

