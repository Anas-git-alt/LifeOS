import { useEffect, useState } from "react";
import { checkinLifeItem, createLifeItem, getLifeItems } from "../api";

const domains = ["deen", "family", "work", "health", "planning"];

export default function LifeItems() {
  const [items, setItems] = useState([]);
  const [domain, setDomain] = useState("planning");
  const [title, setTitle] = useState("");
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
      await createLifeItem({ domain, title: title.trim(), kind: "task", priority: "medium" });
      setTitle("");
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
      {error && <div className="glass-card">{error}</div>}
      <div className="glass-card" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <select value={domain} onChange={(event) => setDomain(event.target.value)}>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="New life item..." />
          <button className="btn btn-primary" onClick={addItem}>
            Add
          </button>
        </div>
      </div>
      <div style={{ display: "grid", gap: 12 }}>
        {items.map((item) => (
          <div key={item.id} className="glass-card">
            <div className="agent-card-header">
              <h3>
                #{item.id} {item.title}
              </h3>
              <span className="badge badge-active">
                {item.domain} / {item.priority}
              </span>
            </div>
            <div className="action-row">
              <button className="btn btn-success" onClick={() => mark(item.id, "done")}>
                Done
              </button>
              <button className="btn btn-danger" onClick={() => mark(item.id, "missed")}>
                Missed
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
