import { useEffect, useState } from "react";
import { getDailyFocusCoach, getTodayAgenda, getWeeklyCommitmentReview, logDailySignal } from "../api";

const EMPTY_SCORECARD = {
  sleep_hours: null,
  meals_count: 0,
  hydration_count: 0,
  training_status: null,
  shutdown_done: false,
  protein_hit: false,
  family_action_done: false,
  top_priority_completed_count: 0,
  rescue_status: "unknown",
};

export default function TodayView() {
  const [agenda, setAgenda] = useState(null);
  const [focusCoach, setFocusCoach] = useState(null);
  const [weeklyReview, setWeeklyReview] = useState(null);
  const [weeklyReviewLoading, setWeeklyReviewLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [activeLog, setActiveLog] = useState("");
  const [sleepHours, setSleepHours] = useState("");
  const [sleepNote, setSleepNote] = useState("");
  const [sleepBedtime, setSleepBedtime] = useState("");
  const [sleepWakeTime, setSleepWakeTime] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      const nextAgenda = await getTodayAgenda();
      setAgenda(nextAgenda);
      setError("");
      getDailyFocusCoach()
        .then(setFocusCoach)
        .catch(() => setFocusCoach(null));
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
              sleep_protocol: result.sleep_protocol || current.sleep_protocol || null,
              streaks: result.streaks || current.streaks || [],
              trend_summary: result.trend_summary || current.trend_summary || null,
            }
          : current
      ));
      setFocusCoach(await getDailyFocusCoach().catch(() => focusCoach));
      setStatus(result.message);
      setError("");
      if (kind === "sleep") {
        setSleepHours("");
        setSleepNote("");
        setSleepBedtime("");
        setSleepWakeTime("");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setActiveLog("");
    }
  }

  async function loadWeeklyReview() {
    try {
      setWeeklyReviewLoading(true);
      setWeeklyReview(await getWeeklyCommitmentReview());
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setWeeklyReviewLoading(false);
    }
  }

  const scorecard = agenda?.scorecard || EMPTY_SCORECARD;
  const rescuePlan = agenda?.rescue_plan;
  const nextPrayer = agenda?.next_prayer;
  const sleepProtocol = agenda?.sleep_protocol;
  const streaks = agenda?.streaks || [];
  const trendSummary = agenda?.trend_summary;

  return (
    <div>
      <header className="page-header">
        <h1>Today</h1>
        <p>Daily accountability board with anchors, rescue plan, and quick logs.</p>
      </header>

      {error && <div className="glass-card status-message status-message-error">{error}</div>}
      {status && <div className="glass-card status-message status-message-success">{status}</div>}

      {agenda && (
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
            <StreaksBlock streaks={streaks} />
            <TrendBlock trendSummary={trendSummary} />
          </div>

          <div className="grid grid-2" style={{ marginBottom: 20 }}>
            <CommitmentRadarBlock items={agenda.top_focus || []} />
            <FocusCoachBlock
              focusCoach={focusCoach}
              weeklyReview={weeklyReview}
              weeklyReviewLoading={weeklyReviewLoading}
              onLoadWeeklyReview={loadWeeklyReview}
              topFocus={agenda.top_focus || []}
            />
          </div>

          <div className="grid grid-2" style={{ marginBottom: 20 }}>
            <SleepProtocolBlock sleepProtocol={sleepProtocol} />
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
                <span>Hours + bedtime + wake</span>
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
              <div className="grid grid-2">
                <div className="form-group">
                  <label htmlFor="today-sleep-bedtime">Bedtime</label>
                  <input
                    id="today-sleep-bedtime"
                    type="time"
                    value={sleepBedtime}
                    onChange={(event) => setSleepBedtime(event.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="today-sleep-wake-time">Wake time</label>
                  <input
                    id="today-sleep-wake-time"
                    type="time"
                    value={sleepWakeTime}
                    onChange={(event) => setSleepWakeTime(event.target.value)}
                  />
                </div>
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
                  onClick={() => submitLog("sleep", {
                    hours: sleepHours ? Number(sleepHours) : null,
                    bedtime: sleepBedtime || null,
                    wake_time: sleepWakeTime || null,
                    note: sleepNote,
                  })}
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

function StreaksBlock({ streaks }) {
  return (
    <div className="glass-card today-highlight-card">
      <div className="panel-card-head">
        <h2>Streaks</h2>
        <span>Current rhythm</span>
      </div>
      {streaks.length === 0 ? (
        <p className="today-highlight-meta">Need a few days of logs before streaks show anything useful.</p>
      ) : (
        <ul className="today-streak-list">
          {streaks.map((metric) => (
            <li key={metric.key} className="today-streak-row">
              <div className="today-streak-main">
                <strong>{metric.label}</strong>
                <span className="today-streak-stats">
                  {metric.current_streak}d streak · {metric.hits_last_7}/7 hits
                </span>
              </div>
              <span className={`today-status-pill today-status-pill-${metric.today_status}`}>
                {metric.today_status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TrendBlock({ trendSummary }) {
  const recentDays = trendSummary?.recent_days || [];
  const bestDay = trendSummary?.best_day;

  return (
    <div className="glass-card today-highlight-card">
      <div className="panel-card-head">
        <h2>7-Day Trend</h2>
        <span>Completed days only</span>
      </div>
      {recentDays.length === 0 ? (
        <p className="today-highlight-meta">Trend summary starts after first completed day lands.</p>
      ) : (
        <>
          <div className="today-trend-summary">
            <div>
              <div className="stat-value">{trendSummary.average_completion_pct}%</div>
              <div className="stat-label">Average anchor completion</div>
            </div>
            <div className="today-highlight-meta">
              Best day: {formatShortDate(bestDay?.date)} ({bestDay?.hits}/{bestDay?.total})
            </div>
          </div>
          <div className="today-trend-days">
            {recentDays.map((day) => (
              <div key={day.date} className="today-trend-day">
                <div className="today-trend-day-header">
                  <span>{formatShortDate(day.date)}</span>
                  <span>{day.hits}/{day.total}</span>
                </div>
                <CompletionBar value={day.completion_pct} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SleepProtocolBlock({ sleepProtocol }) {
  if (!sleepProtocol) {
    return (
      <div className="glass-card today-highlight-card">
        <div className="panel-card-head">
          <h2>Sleep Protocol</h2>
          <span>Targets unavailable</span>
        </div>
        <p className="today-highlight-meta">Set bedtime, wake target, and wind-down checklist in Profile.</p>
      </div>
    );
  }

  return (
    <div className="glass-card today-highlight-card">
      <div className="panel-card-head">
        <h2>Sleep Protocol</h2>
        <span>{sleepProtocol.bedtime_target} → {sleepProtocol.wake_target}</span>
      </div>
      <div className="today-protocol-grid">
        <div className="meta-tag">Bed target {sleepProtocol.bedtime_target}</div>
        <div className="meta-tag">Wake target {sleepProtocol.wake_target}</div>
        <div className="meta-tag">Caffeine cutoff {sleepProtocol.caffeine_cutoff}</div>
        <div className="meta-tag">
          Logged {sleepProtocol.sleep_hours_logged != null ? `${sleepProtocol.sleep_hours_logged}h` : "none"}
        </div>
      </div>
      {(sleepProtocol.bedtime_logged || sleepProtocol.wake_time_logged) && (
        <p className="today-highlight-meta">
          Latest sleep log: {sleepProtocol.bedtime_logged || "?"} → {sleepProtocol.wake_time_logged || "?"}
        </p>
      )}
      {(sleepProtocol.wind_down_checklist || []).length > 0 ? (
        <ul className="today-checklist">
          {sleepProtocol.wind_down_checklist.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="today-highlight-meta">Wind-down checklist empty.</p>
      )}
    </div>
  );
}

function CommitmentRadarBlock({ items }) {
  return (
    <div className="glass-card today-highlight-card">
      <div className="panel-card-head">
        <h2>Commitment Radar</h2>
        <span>{items.length} ranked</span>
      </div>
      {items.length === 0 ? (
        <p className="today-highlight-meta">No tracked commitments surfaced yet.</p>
      ) : (
        <ul className="today-checklist">
          {items.map((item) => (
            <li key={item.id}>
              <strong>#{item.id} {item.title}</strong>
              <div className="today-highlight-meta">{item.focus_reason || item.priority_reason || `${item.domain} / ${item.priority}`}</div>
              <div className="meta-tag" style={{ marginTop: 6 }}>
                AI priority {item.priority_score ?? 50}/100 · {item.priority}
              </div>
              {(item.follow_up_due_at || item.due_at) && (
                <div className="meta-tag" style={{ marginTop: 6 }}>
                  Follow-up {formatDateTime(item.follow_up_due_at || item.due_at)}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FocusCoachBlock({ focusCoach, weeklyReview, weeklyReviewLoading, onLoadWeeklyReview, topFocus }) {
  const topById = Object.fromEntries((topFocus || []).map((item) => [item.id, item]));
  const primary = focusCoach?.primary_item_id ? topById[focusCoach.primary_item_id] : null;
  const deferTitles = (focusCoach?.defer_ids || []).map((itemId) => topById[itemId]?.title || `#${itemId}`);

  return (
    <div className="glass-card today-highlight-card">
      <div className="panel-card-head">
        <h2>AI Focus Coach</h2>
        <span>{focusCoach?.fallback_used ? "fallback" : "ai"}</span>
      </div>
      {focusCoach ? (
        <>
          <p className="today-highlight-value">{primary ? primary.title : "No primary item selected"}</p>
          <ul className="today-checklist">
            <li>{focusCoach.why_now}</li>
            <li>{focusCoach.first_step}</li>
            <li>{focusCoach.nudge_copy}</li>
          </ul>
          <p className="today-highlight-meta">Defer: {deferTitles.length ? deferTitles.join(", ") : "none"}</p>
        </>
      ) : (
        <p className="today-highlight-meta">Coach unavailable right now.</p>
      )}

      <div className="action-row" style={{ marginTop: 16 }}>
        <button className="btn btn-ghost" type="button" onClick={onLoadWeeklyReview} disabled={weeklyReviewLoading}>
          {weeklyReviewLoading ? "Running..." : "Run Weekly Review"}
        </button>
      </div>

      {weeklyReview && (
        <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
          <div className="meta-tag">Weekly review · {weeklyReview.fallback_used ? "fallback" : "ai"}</div>
          <ReviewList title="Wins" items={weeklyReview.wins} />
          <ReviewList title="Stale" items={weeklyReview.stale_commitments} />
          <ReviewList title="Blockers" items={weeklyReview.repeat_blockers} />
          <ReviewList title="At Risk" items={weeklyReview.promises_at_risk} />
          <ReviewList title="Next Week" items={weeklyReview.simplify_next_week} />
        </div>
      )}
    </div>
  );
}

function ReviewList({ title, items }) {
  return (
    <div>
      <strong>{title}</strong>
      <ul style={{ marginTop: 6, paddingLeft: 18, display: "grid", gap: 4 }}>
        {(items || []).slice(0, 3).map((item) => (
          <li key={`${title}-${item}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function CompletionBar({ value }) {
  return (
    <div className="score-bar-wrap" aria-label={`${value}% completion`}>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${value}%` }} />
      </div>
      <span className="score-bar-label">{value}%</span>
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
                {item.domain} / {item.priority} / AI {item.priority_score ?? 50}
              </div>
              {(item.focus_reason || item.priority_reason) && (
                <div style={{ marginTop: 6, color: "var(--text-secondary)", fontSize: 13 }}>
                  {item.focus_reason || item.priority_reason}
                </div>
              )}
              {(item.follow_up_due_at || item.due_at) && (
                <div className="meta-tag" style={{ marginTop: 6 }}>
                  Follow-up {formatDateTime(item.follow_up_due_at || item.due_at)}
                </div>
              )}
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

function formatShortDate(raw) {
  if (!raw) return "Unknown";
  return new Date(raw).toLocaleDateString([], { month: "short", day: "numeric" });
}
