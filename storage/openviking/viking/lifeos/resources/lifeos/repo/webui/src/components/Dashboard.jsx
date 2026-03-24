import { useEffect, useState } from "react";
import { getAgents, getApprovalStats, getHealth, getReadiness } from "../api";

export default function Dashboard({ onChangeToken }) {
  const [health, setHealth] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [stats, setStats] = useState({});
  const [agents, setAgents] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  async function loadData() {
    try {
      const [h, r, s, a] = await Promise.all([getHealth(), getReadiness(), getApprovalStats(), getAgents()]);
      setHealth(h);
      setReadiness(r);
      setStats(s);
      setAgents(a);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <header className="page-header">
        <div className="page-header-row">
          <div>
            <h1>LifeOS Dashboard</h1>
            <p>Production readiness snapshot and active agents.</p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onChangeToken}>
            Change Token
          </button>
        </div>
      </header>

      {error && <div className="glass-card">Backend/API error: {error}</div>}

      <div className="grid grid-4" style={{ marginBottom: 24 }}>
        <StatCard label="Agents" value={agents.length} />
        <StatCard label="Pending Approvals" value={stats.pending || 0} />
        <StatCard label="Health" value={health ? health.status : "unknown"} />
        <StatCard label="Readiness" value={readiness ? readiness.status : "unknown"} />
      </div>

      <h2 style={{ fontSize: 20, marginBottom: 16 }}>Agent Overview</h2>
      <div className="grid grid-2">
        {agents.map((agent) => (
          <div key={agent.id} className="glass-card">
            <div className="agent-card-header">
              <h3>{agent.name}</h3>
              <span className={`badge ${agent.enabled ? "badge-active" : "badge-rejected"}`}>
                {agent.enabled ? "Active" : "Disabled"}
              </span>
            </div>
            <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>{agent.description?.slice(0, 110)}</p>
            <div className="agent-meta">
              <span className="meta-tag">{agent.provider}</span>
              <span className="meta-tag">{agent.model}</span>
              {agent.cadence && <span className="meta-tag">{agent.cadence}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="glass-card">
      <div className="stat-value">{String(value)}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
