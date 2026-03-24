import { useEffect, useRef, useState } from "react";
import { editPrayerCheckin, getPrayerDashboard } from "../api";

const PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"];
const STATUS_OPTIONS = ["on_time", "late", "missed"];
const STATUS_DISPLAY = { on_time: "✅", late: "🕒", missed: "❌", unknown: "❓" };
const STATUS_COLORS = {
    on_time: "var(--color-success)",
    late: "var(--color-warning)",
    missed: "var(--color-danger)",
    unknown: "var(--text-muted)",
};

export default function PrayerDashboard() {
    const [dashboard, setDashboard] = useState(null);
    const [error, setError] = useState("");
    const [editing, setEditing] = useState(null); // {date, prayer}
    const [saving, setSaving] = useState(false);
    const [streakMilestone, setStreakMilestone] = useState(false);
    const prevOnTime = useRef(0);

    useEffect(() => {
        load();
    }, []);

    // Trigger pop animation when on_time crosses a multiple-of-5 milestone
    useEffect(() => {
        const onTime = dashboard?.summary?.on_time || 0;
        if (onTime > 0 && onTime % 5 === 0 && onTime !== prevOnTime.current) {
            setStreakMilestone(true);
            const t = setTimeout(() => setStreakMilestone(false), 600);
            prevOnTime.current = onTime;
            return () => clearTimeout(t);
        }
        prevOnTime.current = onTime;
    }, [dashboard?.summary?.on_time]);

    async function load() {
        try {
            setDashboard(await getPrayerDashboard());
            setError("");
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleEdit(date, prayer, status) {
        setSaving(true);
        try {
            await editPrayerCheckin(date, prayer, status);
            setEditing(null);
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    const summary = dashboard?.summary || {};
    const totalChecked = (summary.on_time || 0) + (summary.late || 0) + (summary.missed || 0) + (summary.unknown || 0);
    const completionRate = totalChecked ? (((summary.on_time || 0) + (summary.late || 0)) / totalChecked * 100).toFixed(1) : 0;
    const onTimeRate = totalChecked ? ((summary.on_time || 0) / totalChecked * 100).toFixed(1) : 0;

    return (
        <div>
            <header className="page-header">
                <h1>🕌 Prayer Dashboard</h1>
                <p>Weekly prayer completion — click any cell to adjust.</p>
            </header>
            {error && <div className="glass-card error-text" style={{ marginBottom: 16 }}>{error}</div>}

            {dashboard && (
                <>
                    <div className="grid grid-4" style={{ marginBottom: 20 }}>
                        <div className="glass-card">
                            <div className="stat-value status-text-success">{onTimeRate}%</div>
                            <div className="stat-label">On-Time Rate</div>
                        </div>
                        <div className="glass-card">
                            <div className="stat-value">{completionRate}%</div>
                            <div className="stat-label">Completion Rate</div>
                        </div>
                        <div className="glass-card">
                            <div className={`stat-value status-text-success${streakMilestone ? ' streak-milestone' : ''}`}>
                                {summary.on_time || 0}
                            </div>
                            <div className="stat-label">On Time</div>
                        </div>
                        <div className="glass-card">
                            <div className="stat-value status-text-danger">{summary.missed || 0}</div>
                            <div className="stat-label">Missed</div>
                        </div>
                    </div>

                    <div className="glass-card" style={{ overflowX: "auto" }}>
                        <table className="prayer-grid-table" id="prayer-grid">
                            <thead>
                                <tr>
                                    <th className="prayer-grid-date">Date</th>
                                    {PRAYERS.map((p) => (
                                        <th key={p} className="prayer-grid-col-head">{p}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {(dashboard.days || []).map((day) => {
                                    const dayLabel = new Date(day.date + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
                                    return (
                                        <tr key={day.date}>
                                            <td className="prayer-grid-date">{dayLabel}</td>
                                            {PRAYERS.map((prayer) => {
                                                const status = day.prayers[prayer];
                                                const isEditing = editing?.date === day.date && editing?.prayer === prayer;
                                                return (
                                                    <td key={prayer} className="prayer-grid-cell">
                                                        {isEditing ? (
                                                            <div className="prayer-edit-popover">
                                                                {STATUS_OPTIONS.map((opt) => (
                                                                    <button
                                                                        key={opt}
                                                                        className="btn btn-ghost"
                                                                        disabled={saving}
                                                                        style={{ padding: "6px 10px", fontSize: 12, minWidth: 0 }}
                                                                        onClick={() => handleEdit(day.date, prayer, opt)}
                                                                    >
                                                                        {STATUS_DISPLAY[opt]} {opt.replace("_", " ")}
                                                                    </button>
                                                                ))}
                                                                <button className="btn btn-ghost" style={{ padding: "6px 8px", fontSize: 11, minWidth: 0, color: "var(--text-muted)" }} onClick={() => setEditing(null)}>✕</button>
                                                            </div>
                                                        ) : (
                                                            <button
                                                                className="prayer-cell-btn"
                                                                onClick={() => setEditing({ date: day.date, prayer })}
                                                                style={{
                                                                    background: status ? `${STATUS_COLORS[status]}1c` : "rgba(255,255,255,0.03)",
                                                                    border: `1px solid ${status ? `${STATUS_COLORS[status]}70` : "var(--border-glass)"}`,
                                                                    color: status ? STATUS_COLORS[status] : "var(--text-muted)",
                                                                    borderRadius: 10,
                                                                    padding: "8px 14px",
                                                                    cursor: "pointer",
                                                                    fontSize: 18,
                                                                    minWidth: 48,
                                                                    transition: "all 0.2s ease",
                                                                }}
                                                                title={`${prayer} on ${day.date}: ${status || "not logged"}`}
                                                            >
                                                                {status ? STATUS_DISPLAY[status] : "·"}
                                                            </button>
                                                        )}
                                                    </td>
                                                );
                                            })}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    <div style={{ marginTop: 16, display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12, color: "var(--text-secondary)" }}>
                        <span>✅ On time</span>
                        <span>🕒 Late</span>
                        <span>❌ Missed</span>
                        <span>❓ Unknown</span>
                        <span>· Not logged</span>
                    </div>
                </>
            )}
        </div>
    );
}
