import { useEffect, useState } from "react";
import "./App.css";
import AgentConfig from "./components/AgentConfig";
import AgentList from "./components/AgentList";
import AgentWizard from "./components/AgentWizard";
import ApprovalQueue from "./components/ApprovalQueue";
import Dashboard from "./components/Dashboard";
import GlobalSettings from "./components/GlobalSettings";
import GoalProgress from "./components/GoalProgress";
import LifeItems from "./components/LifeItems";
import JobsManager from "./components/JobsManager";
import PrayerDashboard from "./components/PrayerDashboard";
import ProfileSettings from "./components/ProfileSettings";
import ProviderConfig from "./components/ProviderConfig";
import QuranLog from "./components/QuranLog";
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
  "prayer-dashboard": {
    title: "Prayer Dashboard",
    subtitle: "Weekly prayer completion grid — adjust any prayer status.",
  },
  quran: {
    title: "Quran Log",
    subtitle: "Track your reading page by page with auto-resume bookmark.",
  },
  life: {
    title: "Life Items",
    subtitle: "Capture and review tasks across deen, family, work, and health.",
  },
  "goal-progress": {
    title: "Goal Progress",
    subtitle: "Track progress, check-ins, and completion over time.",
  },
  agents: {
    title: "Agents",
    subtitle: "Manage roles, models, cadence, and orchestration quality.",
  },
  "agent-create": {
    title: "Spawn Agent",
    subtitle: "Create new agents from a guided form with optional approval queue.",
  },
  jobs: {
    title: "Jobs",
    subtitle: "Manage all cron jobs globally and per agent with run visibility.",
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
  settings: {
    title: "Global Settings",
    subtitle: "Control reporting filters, autonomy toggles, and runtime defaults.",
  },
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [selectedGoalId, setSelectedGoalId] = useState(null);
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

  const handleGoalSelect = (itemId) => {
    setSelectedGoalId(itemId);
    setPage("goal-progress");
  };

  const renderPage = () => {
    switch (page) {
      case "dashboard":
        return <Dashboard onChangeToken={() => setShowTokenEditor(true)} />;
      case "today":
        return <TodayView />;
      case "prayer-dashboard":
        return <PrayerDashboard />;
      case "quran":
        return <QuranLog />;
      case "life":
        return <LifeItems onGoalSelect={handleGoalSelect} />;
      case "goal-progress":
        return <GoalProgress itemId={selectedGoalId} onBack={() => setPage("life")} />;
      case "agents":
        return <AgentList onSelect={handleAgentSelect} />;
      case "agent-create":
        return <AgentWizard />;
      case "jobs":
        return <JobsManager />;
      case "agent-config":
        return <AgentConfig agentName={selectedAgent} onBack={() => setPage("agents")} />;
      case "approvals":
        return <ApprovalQueue />;
      case "providers":
        return <ProviderConfig />;
      case "profile":
        return <ProfileSettings />;
      case "settings":
        return <GlobalSettings />;
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
                  className={`quick-nav-btn ${page === "prayer-dashboard" ? "active" : ""}`}
                  onClick={() => setPage("prayer-dashboard")}
                >
                  🕌 Prayer
                </button>
                <button
                  className={`quick-nav-btn ${page === "quran" ? "active" : ""}`}
                  onClick={() => setPage("quran")}
                >
                  📖 Quran
                </button>
                <button
                  className={`quick-nav-btn ${page === "agents" ? "active" : ""}`}
                  onClick={() => setPage("agents")}
                >
                  Agents
                </button>
                <button
                  className={`quick-nav-btn ${page === "jobs" ? "active" : ""}`}
                  onClick={() => setPage("jobs")}
                >
                  Jobs
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
