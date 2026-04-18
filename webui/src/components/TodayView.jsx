import { useEffect, useState } from "react";
import { getTodayAgenda, logDailySignal } from "../api";

export default function TodayView() {
  const [agenda, setAgenda] = useState(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [activeLog, setActiveLog] = useState("");
  const [sleepHours, setSleepHours] = useState("");
  const [sleepNote, setSleepNote] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setAgenda(await getTodayAgenda());
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function submitLog(kind, payload = {}, loadingKey = kind) {
    try {
      setActiveLog(loadingKey);
      const result = await logDailySignal({ kind, ...payload });
      setAgenda((current) => (
        current
          ? {
              ...current,
              scorecard: result.scorecard,
              rescue_plan: result.rescue_plan,
            }
          : current
      ));
      setStatus(result.message);
      setError("");
      if (kind === "sleep") {
        setSleepHours("");
        setSleepNote("");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setActiveLog("");
    }
  }

  const scorecard = agenda?.scorecard;
  const rescuePlan = agenda?.rescue_plan;
  const nextPrayer = agenda?.next_prayer;

  return (
    <div>
      <header className="page-header">
        <h1>Today</h1>
        <p>Daily accountability board with anchors, rescue plan, and quick logs.</p>
      </header>

      {error && <div className="glass-card status-message status-message-error">{error}</div>}
      {status && <div className="glass-card status-message status-message-success">{status}</div>}

      {agenda && scorecard && (
        <>
          <div className="grid grid-4 today-score-grid" style={{ marginBottom: 20 }}>
            <ScoreCardStat label="Timezone" value={agenda.timezone} />
            <ScoreCardStat label="Now" value={formatDateTime(agenda.now)} />
            <ScoreCardStat label="Sleep" value={scorecard.sleep_hours != null ? `${scorecard.sleep_hours}h` : "Not logged"} />
            <ScoreCardStat label="Meals" value={String(scorecard.meals_count)} />
            <ScoreCardStat label="Water" value={String(scorecard.hydration_count)} />
            <ScoreCardStat label="Training" value={scorecard.training_status || "Unset"} />
            <ScoreCardStat label="Shutdown" value={scorecard.shutdown_done ? "Done" : "Pending"} />
            <ScoreCardStat label="Protein" value={scorecard.protein_hit ? "Hit" : "Pending"} />
            <ScoreCardStat label="Family" value={scorecard.family_action_done ? "Done" : "Pending"} />
            <ScoreCardStat label="Priorities" value={String(scorecard.top_priority_completed_count)} />
            <ScoreCardStat label="Open Domains" value={String(Object.keys(agenda.domain_summary || {}).length)} />
            <ScoreCardStat label="Inbox Ready" value={String(agenda.intake_summary?.ready || 0)} />
          </div>

          <div className="grid grid-2" style={{ marginBottom: 20 }}>
            <div className="glass-card today-highlight-card">
              <div className="panel-card-head">
                <h2>Next Prayer</h2>
                <span>{nextPrayer ? nextPrayer.name : "No upcoming prayer"}</span>
              </div>
              {nextPrayer ? (
                <>
                  <p className="today-highlight-value">{nextPrayer.name}</p>
                  <p className="today-highlight-meta">
                    {formatTime(nextPrayer.starts_at)} → {formatTime(nextPrayer.ends_at)}
                  </p>
                </>
              ) : (
                <p className="today-highlight-meta">Prayer context unavailable right now.</p>
              )}
            </div>

            <div className="glass-card today-highlight-card">
              <div className="panel-card-head">
                <h2>Rescue Plan</h2>
                <span className={`badge ${rescueBadgeClass(rescuePlan?.status)}`}>
                  {rescuePlan?.status || scorecard.rescue_status}
                </span>
              </div>
              <p className="today-highlight-value">{rescuePlan?.headline || "No rescue signal."}</p>
              {(rescuePlan?.actions || []).length > 0 ? (
                <ul className="today-checklist">
                  {rescuePlan.actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              ) : (
                <p className="today-highlight-meta">Keep current rhythm. No rescue actions needed yet.</p>
              )}
            </div>
          </div>

          <div className="grid grid-2" style={{ marginBottom: 20 }}>
            <div className="glass-card">
              <div className="panel-card-head">
                <h2>Quick Logs</h2>
                <span>Fast buttons for anchors</span>
              </div>
              <div className="today-quick-grid">
                <QuickLogButton
                  label="Meal +1"
                  kind="meal"
                  activeLog={activeLog}
                  onClick={() => submitLog("meal", { count: 1 }, "meal")}
                />
                <QuickLogButton
                  label="Protein Meal"
                  kind="meal-protein"
                  activeLog={activeLog}
                  onClick={() => submitLog("meal", { count: 1, protein_hit: true }, "meal-protein")}
                />
                <QuickLogButton
                  label="Water +1"
                  kind="hydration"
                  activeLog={activeLog}
                  onClick={() => submitLog("hydration", { count: 1 }, "hydration")}
                />
                <QuickLogButton
                  label="Train"
                  kind="training"
                  activeLog={activeLog}
                  onClick={() => submitLog("training", { status: "done" }, "training")}
                />
                <QuickLogButton
                  label="Rest Day"
                  kind="training-rest"
                  activeLog={activeLog}
                  onClick={() => submitLog("training", { status: "rest" }, "training-rest")}
                />
                <QuickLogButton
                  label="Family Action"
                  kind="family"
                  activeLog={activeLog}
                  onClick={() => submitLog("family", { done: true }, "family")}
                />
                <QuickLogButton
                  label="Priority Done"
                  kind="priority"
                  activeLog={activeLog}
                  onClick={() => submitLog("priority", { count: 1 }, "priority")}
                />
                <QuickLogButton
                  label="Shutdown"
                  kind="shutdown"
                  activeLog={activeLog}
                  onClick={() => submitLog("shutdown", { done: true }, "shutdown")}
                />
              </div>
            </div>

            <div className="glass-card">
              <div className="panel-card-head">
                <h2>Sleep Log</h2>
                <span>Hours + note</span>
              </div>
              <div className="form-group">
                <label htmlFor="today-sleep-hours">Sleep hours</label>
                <input
                  id="today-sleep-hours"
                  type="number"
                  min="0"
                  max="24"
                  step="0.25"
                  value={sleepHours}
                  onChange={(event) => setSleepHours(event.target.value)}
                  placeholder="7.5"
                />
              </div>
              <div className="form-group">
                <label htmlFor="today-sleep-note">Sleep note</label>
                <input
                  id="today-sleep-note"
                  type="text"
                  value={sleepNote}
                  onChange={(event) => setSleepNote(event.target.value)}
                  placeholder="Bed late, woke once, felt good"
                />
              </div>
              <div className="action-row">
                <button
                  className="btn btn-primary"
                  onClick={() => submitLog("sleep", { hours: sleepHours ? Number(sleepHours) : null, note: sleepNote })}
                  disabled={activeLog === "sleep"}
                >
                  {activeLog === "sleep" ? "Saving..." : "Log Sleep"}
                </button>
              </div>
            </div>
          </div>

          <div className="grid grid-2" style={{ marginBottom: 20 }}>
            <AgendaBlock title="Due Today" items={agenda.due_today || []} emptyLabel="No due items today." />
            <AgendaBlock title="Overdue" items={agenda.overdue || []} emptyLabel="No overdue items right now." />
          </div>

          <div className="grid grid-2">
            <AgendaBlock title="Top Focus" items={agenda.top_focus || []} emptyLabel="No focus items yet." />
            <InboxBlock title="Inbox Ready" items={agenda.ready_intake || []} summary={agenda.intake_summary || {}} />
          </div>
        </>
      )}
    </div>
  );
}

function ScoreCardStat({ label, value }) {
  return (
    <div className="glass-card today-stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

function QuickLogButton({ label, kind, activeLog, onClick }) {
  return (
    <button
      className="quick-nav-btn"
      type="button"
      disabled={activeLog === kind}
      onClick={onClick}
    >
      {activeLog === kind ? "Saving..." : label}
    </button>
  );
}

function AgendaBlock({ title, items, emptyLabel }) {
  return (
    <div className="glass-card">
      <h3 style={{ marginBottom: 12 }}>{title}</h3>
      {items.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>{emptyLabel}</p>
      ) : (
        <ul style={{ display: "grid", gap: 8 }}>
          {items.map((item) => (
            <li key={item.id} style={{ listStyle: "none" }}>
              #{item.id} {item.title}
              <div className="meta-tag" style={{ marginTop: 4 }}>
                {item.domain} / {item.priority}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function InboxBlock({ title, items, summary }) {
  return (
    <div className="glass-card">
      <h3 style={{ marginBottom: 12 }}>{title}</h3>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        <span className="meta-tag">ready {summary.ready || 0}</span>
        <span className="meta-tag">clarifying {summary.clarifying || 0}</span>
        <span className="meta-tag">parked {summary.parked || 0}</span>
      </div>
      {items.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>Inbox clear enough for today.</p>
      ) : (
        <ul style={{ display: "grid", gap: 8 }}>
          {items.map((item) => (
            <li key={item.id} style={{ listStyle: "none" }}>
              #{item.id} {item.title || item.raw_text}
              <div className="meta-tag" style={{ marginTop: 4 }}>
                {item.status} / {item.domain} / {item.kind}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function rescueBadgeClass(status) {
  if (status === "on_track") return "badge-approved";
  if (status === "rescue") return "badge-rejected";
  return "badge-active";
}

function formatDateTime(raw) {
  if (!raw) return "Unknown";
  return new Date(raw).toLocaleString();
}

function formatTime(raw) {
  if (!raw) return "Unknown";
  return new Date(raw).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
