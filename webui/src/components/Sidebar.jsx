import { useState } from "react";

export default function Sidebar({ currentPage, onNavigate }) {
  const [open, setOpen] = useState(false);

  const navGroups = [
    {
      title: "Overview",
      items: [
        { id: "dashboard", icon: "DB", label: "Dashboard" },
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
        { id: "approvals", icon: "AP", label: "Approvals" },
        { id: "providers", icon: "PV", label: "Providers" },
      ],
    },
    {
      title: "Account",
      items: [{ id: "profile", icon: "ME", label: "Profile" }],
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

        <div className="sidebar-footer">
          <span className="status-dot" />
          <span>Workspace connected</span>
        </div>
      </aside>
    </>
  );
}
