import { useEffect, useMemo, useState } from "react";
import "./App.css";
import AgentConfig from "./components/AgentConfig";
import AgentList from "./components/AgentList";
import AgentWizard from "./components/AgentWizard";
import ApprovalQueue from "./components/ApprovalQueue";
import ExperimentDashboard from "./components/ExperimentDashboard";
import GlobalSettings from "./components/GlobalSettings";
import GoalProgress from "./components/GoalProgress";
import InboxView from "./components/InboxView";
import LifeItems from "./components/LifeItems";
import JobsManager from "./components/JobsManager";
import MissionControl from "./components/MissionControl";
import PrayerDashboard from "./components/PrayerDashboard";
import ProfileSettings from "./components/ProfileSettings";
import ProviderConfig from "./components/ProviderConfig";
import QuranLog from "./components/QuranLog";
import TodayView from "./components/TodayView";
import TokenBanner from "./components/TokenBanner";
import WikiView from "./components/WikiView";

const NAV_GROUPS = [
  {
    title: "Overview",
    items: [
      { id: "dashboard", icon: "⊞", label: "Mission Control" },
      { id: "today", icon: "◈", label: "Today" },
      { id: "inbox", icon: "✦", label: "Inbox" },
      { id: "wiki", icon: "◇", label: "Wiki" },
      { id: "prayer-dashboard", icon: "☽", label: "Prayer" },
      { id: "quran", icon: "◎", label: "Quran" },
      { id: "life", icon: "⋮", label: "Life Items" },
    ],
  },
  {
    title: "Automation",
    items: [
      { id: "agents", icon: "⬡", label: "Agents" },
      { id: "agent-create", icon: "+", label: "Spawn Agent" },
      { id: "jobs", icon: "⏱", label: "Jobs" },
      { id: "approvals", icon: "◇", label: "Approvals" },
      { id: "providers", icon: "⬢", label: "Providers" },
      { id: "experiments", icon: "🧪", label: "Experiments" },
    ],
  },
  {
    title: "Account",
    items: [
      { id: "profile", icon: "○", label: "Profile" },
      { id: "settings", icon: "⚙", label: "Settings" },
    ],
  },
];

const PAGE_META = {
  dashboard: {
    title: "Mission Control",
    subtitle: "Realtime pulse across system health, approvals, jobs, and agent activity.",
  },
  today: {
    title: "Today Focus",
    subtitle: "Plan the day with priorities, due items, and current context.",
  },
  inbox: {
    title: "Inbox",
    subtitle: "Capture ideas, promises, and life improvements before they get lost.",
  },
  wiki: {
    title: "Wiki Context",
    subtitle: "Review-first Obsidian memory from meetings, replies, and shared context.",
  },
  "prayer-dashboard": {
    title: "Prayer Dashboard",
    subtitle: "Weekly prayer completion grid with quick status updates.",
  },
  quran: {
    title: "Quran Log",
    subtitle: "Track reading page by page with auto-resume bookmark.",
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
  experiments: {
    title: "Experiments",
    subtitle: "Shadow A/B test log — live provider health, scores, and promotion candidates.",
  },
};

function getAllNavItems() {
  return NAV_GROUPS.flatMap((group) => group.items);
}

function PageSurface({ hasToken, showTokenEditor, setShowTokenEditor, setHasToken, renderPage }) {
  return (
    <>
      {(showTokenEditor || !hasToken) && (
        <TokenBanner
          canClose={hasToken}
          onClose={() => setShowTokenEditor(false)}
          onValidToken={() => {
            setHasToken(true);
            setShowTokenEditor(false);
          }}
          onInvalidToken={() => {
            setHasToken(false);
            setShowTokenEditor(true);
          }}
        />
      )}
      {renderPage()}
    </>
  );
}

function NavPills({ page, setPage }) {
  return (
    <nav className="ui-nav-pills compact" aria-label="Main navigation">
      {NAV_GROUPS.map((group) => (
        <div key={group.title} style={{ display: "contents" }}>
          <p style={{ fontSize: "10.5px", letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)", padding: "8px 4px 3px", fontWeight: 600 }}>
            {group.title}
          </p>
          {group.items.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "active" : ""}
              onClick={() => setPage(item.id)}
              aria-current={page === item.id ? "page" : undefined}
            >
              <span aria-hidden="true" style={{ fontSize: "14px", lineHeight: 1 }}>{item.icon}</span>
              <strong>{item.label}</strong>
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

export default function App() {
  const [page, setPage] = useState("today");
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [selectedGoalId, setSelectedGoalId] = useState(null);
  const [hasToken, setHasToken] = useState(() => Boolean((localStorage.getItem("lifeos_token") || "").trim()));
  const [showTokenEditor, setShowTokenEditor] = useState(() => !Boolean((localStorage.getItem("lifeos_token") || "").trim()));

  useEffect(() => {
    localStorage.removeItem("lifeos_ui_variant");

    const syncTokenState = () => {
      setHasToken(Boolean((localStorage.getItem("lifeos_token") || "").trim()));
    };

    window.addEventListener("storage", syncTokenState);
    return () => window.removeEventListener("storage", syncTokenState);
  }, []);

  const meta = PAGE_META[page] || PAGE_META.dashboard;

  const renderPage = useMemo(() => {
    const handleAgentSelect = (agentName) => {
      setSelectedAgent(agentName);
      setPage("agent-config");
    };

    const handleGoalSelect = (itemId) => {
      setSelectedGoalId(itemId);
      setPage("goal-progress");
    };

    return () => {
      switch (page) {
        case "dashboard":
          return <MissionControl hasToken={hasToken} onNavigate={setPage} onChangeToken={() => setShowTokenEditor(true)} />;
        case "today":
          return <TodayView />;
        case "inbox":
          return <InboxView />;
        case "wiki":
          return <WikiView />;
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
        case "experiments":
          return <ExperimentDashboard />;
        case "profile":
          return <ProfileSettings />;
        case "settings":
          return <GlobalSettings />;
        default:
          return <MissionControl hasToken={hasToken} onNavigate={setPage} onChangeToken={() => setShowTokenEditor(true)} />;
      }
    };
  }, [hasToken, page, selectedAgent, selectedGoalId]);

  return (
    <div className="ui-shell ui-shell-zen ui-shell-single">
      <header className="ui-zen-header">
        <div>
          <p className="topbar-kicker">LifeOS · v4</p>
          <h1 style={{ fontFamily: "var(--font-display)", fontWeight: 400 }}>{meta.title}</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: "13px", marginTop: 2 }}>{meta.subtitle}</p>
        </div>
        <button className="btn btn-ghost" onClick={() => setPage("today")}>
          Today ↗
        </button>
      </header>

      <div className="ui-zen-body">
        <aside className="ui-zen-nav">
          <div style={{ paddingLeft: 4, marginBottom: 12 }}>
            <span style={{ fontFamily: "var(--font-display)", fontSize: 17, letterSpacing: "-0.01em" }}>☽ LifeOS</span>
          </div>
          <NavPills page={page} setPage={setPage} />
        </aside>

        <section className="ui-content-wide">
          <div key={page} style={{ animation: "pageIn 0.2s cubic-bezier(0.16,1,0.3,1)" }}>
            <PageSurface
              hasToken={hasToken}
              showTokenEditor={showTokenEditor}
              setShowTokenEditor={setShowTokenEditor}
              setHasToken={setHasToken}
              renderPage={renderPage}
            />
          </div>
        </section>
      </div>

      <footer className="ui-zen-footer">
        <span className={`status-dot ${hasToken ? "status-dot-success" : "status-dot-danger"}`} />
        <span>{hasToken ? "Workspace connected" : "Disconnected"}</span>
        <button className="btn btn-ghost" onClick={() => setPage("settings")}>
          Settings
        </button>
      </footer>
    </div>
  );
}
