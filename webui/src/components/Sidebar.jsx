import { useState } from "react";

export default function Sidebar({ currentPage, onNavigate, isConnected = false }) {
  const [open, setOpen] = useState(false);

  const navGroups = [
    {
      title: "Overview",
      items: [
        { id: "dashboard", icon: "MC", label: "Mission Control" },
        { id: "today", icon: "TD", label: "Today" },
        { id: "prayer-dashboard", icon: "🕌", label: "Prayer" },
        { id: "quran", icon: "📖", label: "Quran" },
        { id: "life", icon: "LF", label: "Life Items" },
      ],
    },
    {
      title: "Automation",
      items: [
        { id: "agents", icon: "AG", label: "Agents" },
        { id: "agent-create", icon: "NEW", label: "Spawn Agent" },
        { id: "jobs", icon: "JB", label: "Jobs" },
        { id: "approvals", icon: "AP", label: "Approvals" },
        { id: "providers", icon: "PV", label: "Providers" },
      ],
    },
    {
      title: "Account",
      items: [
        { id: "profile", icon: "ME", label: "Profile" },
        { id: "settings", icon: "CFG", label: "Settings" },
      ],
    },
  ];

  return (
    <>
      <button className="mobile-nav-toggle" onClick={() => setOpen((value) => !value)}>
        Menu
      </button>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-logo">
          <div className="logo-mark">LifeOS</div>
          <div className="logo-sub">Control panel</div>
        </div>

        <nav className="sidebar-nav" aria-label="Sidebar navigation">
          {navGroups.map((group) => (
            <section key={group.title} className="sidebar-group">
              <p className="sidebar-group-title">{group.title}</p>
              {group.items.map((item) => (
                <button
                  key={item.id}
                  className={`sidebar-btn ${currentPage === item.id ? "active" : ""}`}
                  onClick={() => {
                    onNavigate(item.id);
                    setOpen(false);
                  }}
                >
                  <span className="sidebar-icon">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              ))}
            </section>
          ))}
        </nav>

        <div className={`sidebar-footer ${isConnected ? "sidebar-footer-connected" : "sidebar-footer-disconnected"}`}>
          <span className={`status-dot ${isConnected ? "status-dot-success" : "status-dot-danger"}`} />
          <span>{isConnected ? "Workspace connected" : "Workspace disconnected"}</span>
        </div>
      </aside>
    </>
  );
}
