import { useEffect, useState } from "react";
import "./App.css";
import AgentConfig from "./components/AgentConfig";
import AgentList from "./components/AgentList";
import ApprovalQueue from "./components/ApprovalQueue";
import Dashboard from "./components/Dashboard";
import LifeItems from "./components/LifeItems";
import ProfileSettings from "./components/ProfileSettings";
import ProviderConfig from "./components/ProviderConfig";
import Sidebar from "./components/Sidebar";
import TodayView from "./components/TodayView";
import TokenBanner from "./components/TokenBanner";

const PAGE_META = {
  dashboard: {
    title: "Command Center",
    subtitle: "Track system health, approvals, and active agents in one place.",
  },
  today: {
    title: "Today Focus",
    subtitle: "Plan the day with priorities, due items, and current context.",
  },
  life: {
    title: "Life Items",
    subtitle: "Capture and review tasks across deen, family, work, and health.",
  },
  agents: {
    title: "Agents",
    subtitle: "Manage roles, models, cadence, and orchestration quality.",
  },
  "agent-config": {
    title: "Agent Configuration",
    subtitle: "Adjust selected agent behavior without leaving your flow.",
  },
  approvals: {
    title: "Approval Queue",
    subtitle: "Clear pending decisions with confidence and visibility.",
  },
  providers: {
    title: "Provider Setup",
    subtitle: "Configure providers, defaults, and model capabilities.",
  },
  profile: {
    title: "Profile",
    subtitle: "Personal preferences, account settings, and secure defaults.",
  },
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [hasToken, setHasToken] = useState(() => Boolean((localStorage.getItem("lifeos_token") || "").trim()));
  const [showTokenEditor, setShowTokenEditor] = useState(() => !Boolean((localStorage.getItem("lifeos_token") || "").trim()));

  useEffect(() => {
    document.documentElement.dataset.theme = "charcoal";
    return () => {
      delete document.documentElement.dataset.theme;
    };
  }, []);

  const activePageMeta = PAGE_META[page] || PAGE_META.dashboard;

  const handleAgentSelect = (agentName) => {
    setSelectedAgent(agentName);
    setPage("agent-config");
  };

  const renderPage = () => {
    switch (page) {
      case "dashboard":
        return <Dashboard onChangeToken={() => setShowTokenEditor(true)} />;
      case "today":
        return <TodayView />;
      case "life":
        return <LifeItems />;
      case "agents":
        return <AgentList onSelect={handleAgentSelect} />;
      case "agent-config":
        return <AgentConfig agentName={selectedAgent} onBack={() => setPage("agents")} />;
      case "approvals":
        return <ApprovalQueue />;
      case "providers":
        return <ProviderConfig />;
      case "profile":
        return <ProfileSettings />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="app-layout">
      <Sidebar currentPage={page} onNavigate={setPage} />
      <main className="main-content">
        <header className="topbar glass-card">
          <div className="topbar-title-block">
            <p className="topbar-kicker">LifeOS Workspace</p>
            <h1>{activePageMeta.title}</h1>
            <p>{activePageMeta.subtitle}</p>
          </div>
          <div className="topbar-tools">
            <div className="topbar-search-wrap">
              <input type="search" placeholder="Search items, agents, providers..." aria-label="Search" />
            </div>
            <div className="topbar-actions">
              <button className="btn btn-ghost" onClick={() => setPage("today")}>
                Today
              </button>
              <button className="btn btn-primary" onClick={() => setPage("life")}>
                Add Focus
              </button>
            </div>
          </div>
        </header>

        <div className="workspace-grid">
          <section className="workspace-main">
            {(showTokenEditor || !hasToken) && (
              <TokenBanner
                canClose={hasToken}
                onClose={() => setShowTokenEditor(false)}
                onValidToken={() => {
                  setHasToken(true);
                  setShowTokenEditor(false);
                }}
              />
            )}
            {renderPage()}
          </section>

          <aside className="workspace-rail">
            <section className="glass-card panel-card">
              <div className="panel-card-head">
                <h2>Quick Navigation</h2>
                <span>Core areas</span>
              </div>
              <div className="quick-nav-grid">
                <button
                  className={`quick-nav-btn ${page === "dashboard" ? "active" : ""}`}
                  onClick={() => setPage("dashboard")}
                >
                  Dashboard
                </button>
                <button
                  className={`quick-nav-btn ${page === "agents" ? "active" : ""}`}
                  onClick={() => setPage("agents")}
                >
                  Agents
                </button>
                <button
                  className={`quick-nav-btn ${page === "approvals" ? "active" : ""}`}
                  onClick={() => setPage("approvals")}
                >
                  Approvals
                </button>
                <button
                  className={`quick-nav-btn ${page === "providers" ? "active" : ""}`}
                  onClick={() => setPage("providers")}
                >
                  Providers
                </button>
              </div>
            </section>
          </aside>
        </div>
      </main>
    </div>
  );
}
