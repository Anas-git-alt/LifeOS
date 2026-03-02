import { useEffect, useState } from "react";
import { getCapabilities, getProviders } from "../api";

export default function ProviderConfig() {
  const [providers, setProviders] = useState([]);
  const [capabilities, setCapabilities] = useState({});

  useEffect(() => {
    getProviders().then(setProviders).catch(console.error);
    getCapabilities().then(setCapabilities).catch(console.error);
  }, []);

  return (
    <div>
      <header className="page-header">
        <h1>LLM Providers</h1>
        <p>Provider availability and integration capability status.</p>
      </header>

      <div className="grid grid-2">
        {providers.map((provider) => (
          <div key={provider.name} className="glass-card">
            <div className="agent-card-header">
              <h3>{provider.name.toUpperCase()}</h3>
              <span className={`badge ${provider.available ? "badge-approved" : "badge-rejected"}`}>
                {provider.available ? "Configured" : "No API Key"}
              </span>
            </div>
            <div className="agent-meta">
              <span className="meta-tag">{provider.default_model}</span>
              <span className="meta-tag">{provider.base_url}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="glass-card" style={{ marginTop: 20 }}>
        <h3 style={{ marginBottom: 12 }}>Capability Status</h3>
        <div className="agent-meta">
          {Object.entries(capabilities).map(([name, info]) => (
            <span key={name} className={`badge ${info.enabled ? "badge-approved" : "badge-rejected"}`}>
              {name}: {info.enabled ? "enabled" : info.reason || "disabled"}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
