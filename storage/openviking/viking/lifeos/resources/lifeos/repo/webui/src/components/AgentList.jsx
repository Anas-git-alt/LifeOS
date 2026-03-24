import { useState, useEffect } from "react";
import { getAgents, deleteAgent } from "../api";

export default function AgentList({ onSelect }) {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadAgents();
  }, []);

  async function loadAgents() {
    try {
      setAgents(await getAgents());
    } catch (error) {
      console.error("Failed to load agents:", error);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(name) {
    if (!confirm(`Delete agent "${name}"?`)) return;
    try {
      await deleteAgent(name);
      loadAgents();
    } catch (error) {
      alert(`Error: ${error.message}`);
    }
  }

  if (loading) {
    return (
      <div className="empty-state">
        <p>Loading agents...</p>
      </div>
    );
  }

  return (
    <div>
      <header className="page-header">
        <h1>Agents</h1>
        <p>Manage models, provider routing, cadence, and execution settings.</p>
      </header>

      {agents.length === 0 ? (
        <div className="empty-state">
          <p>No agents configured yet. They will be seeded on first backend startup.</p>
        </div>
      ) : (
        <div className="grid grid-2">
          {agents.map((agent) => (
            <div key={agent.id} className="glass-card">
              <div className="agent-card-header">
                <h3>{agent.name}</h3>
                <span className={`badge ${agent.enabled ? "badge-active" : "badge-rejected"}`}>
                  {agent.enabled ? "Active" : "Disabled"}
                </span>
              </div>
              <p style={{ color: "var(--text-secondary)", fontSize: 14, marginBottom: 8 }}>
                {agent.description?.slice(0, 120)}
              </p>
              <div className="agent-meta">
                <span className="meta-tag">Provider: {agent.provider}</span>
                <span className="meta-tag">Model: {agent.model?.split("/").pop()}</span>
                {agent.discord_channel && <span className="meta-tag">Channel: #{agent.discord_channel}</span>}
                {agent.cadence && <span className="meta-tag">Cadence: {agent.cadence}</span>}
              </div>
              <div className="action-row">
                <button className="btn btn-primary" onClick={() => onSelect(agent.name)}>
                  Configure
                </button>
                <button className="btn btn-ghost" onClick={() => handleDelete(agent.name)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
