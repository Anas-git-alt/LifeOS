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
              <span className={`badge ${providerBadgeClass(provider)}`}>
                {providerBadgeText(provider)}
              </span>
            </div>
            <div className="agent-meta">
              <span className="meta-tag">{provider.default_model}</span>
              <span className="meta-tag">{provider.base_url}</span>
              {provider.free_mode_reason && <span className="meta-tag">{provider.free_mode_reason}</span>}
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

function providerBadgeClass(provider) {
  if (!provider.available) return "badge-rejected";
  if (provider.free_mode_allowed === false) return "badge-pending";
  return "badge-approved";
}

function providerBadgeText(provider) {
  if (!provider.available) return "No API Key";
  if (provider.free_mode_allowed === false) return "Blocked by free mode";
  return "Free-mode ready";
}
