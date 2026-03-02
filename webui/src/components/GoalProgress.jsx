import { useEffect, useState } from "react";
import { getGoalProgress, checkinLifeItem } from "../api";

export default function GoalProgress({ itemId, onBack }) {
    const [data, setData] = useState(null);
    const [error, setError] = useState("");

    useEffect(() => {
        if (itemId) load();
    }, [itemId]);

    async function load() {
        try {
            setData(await getGoalProgress(itemId));
            setError("");
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleCheckin(result) {
        try {
            await checkinLifeItem(itemId, result, "");
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    if (!data) {
        return (
            <div>
                <header className="page-header">
                    <div className="page-header-row">
                        <h1>Goal Progress</h1>
                        {onBack && <button className="btn btn-ghost" onClick={onBack}>← Back</button>}
                    </div>
                </header>
                {error ? (
                    <div className="glass-card" style={{ color: "var(--accent-red)" }}>{error}</div>
                ) : (
                    <div className="glass-card">Loading...</div>
                )}
            </div>
        );
    }

    const item = data.item;
    const total = data.checkin_count || 1;
    const donePct = ((data.done_count / Math.max(total, 1)) * 100).toFixed(1);

    return (
        <div>
            <header className="page-header">
                <div className="page-header-row">
                    <div>
                        <h1>{item.title}</h1>
                        <p>
                            {item.domain} / {item.kind} / {item.priority}
                            {item.source_agent && (
                                <span style={{ marginLeft: 12 }}>
                                    <span className="meta-tag">Created by: {item.source_agent}</span>
                                </span>
                            )}
                        </p>
                    </div>
                    {onBack && <button className="btn btn-ghost" onClick={onBack}>← Back</button>}
                </div>
            </header>

            {error && <div className="glass-card" style={{ color: "var(--accent-red)", marginBottom: 16 }}>{error}</div>}

            {/* Stats */}
            <div className="grid grid-4" style={{ marginBottom: 20 }}>
                <div className="glass-card">
                    <div className="stat-value" style={{ color: "var(--accent-gold)" }}>{data.days_since_start ?? "—"}</div>
                    <div className="stat-label">Days Since Start</div>
                </div>
                <div className="glass-card">
                    <div className="stat-value">{data.done_count}</div>
                    <div className="stat-label">Completed</div>
                </div>
                <div className="glass-card">
                    <div className="stat-value">{data.partial_count}</div>
                    <div className="stat-label">Partial</div>
                </div>
                <div className="glass-card">
                    <div className="stat-value" style={{ color: "var(--accent-red)" }}>{data.missed_count}</div>
                    <div className="stat-label">Missed</div>
                </div>
            </div>

            {/* Progress bar */}
            <div className="glass-card" style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 13, color: "var(--text-secondary)" }}>
                    <span>{data.checkin_count} check-ins</span>
                    <span>{donePct}% completion rate</span>
                </div>
                <div style={{
                    height: 10,
                    borderRadius: 99,
                    background: "rgba(255,255,255,0.06)",
                    overflow: "hidden",
                    border: "1px solid var(--border-glass)",
                }}>
                    <div style={{
                        height: "100%",
                        width: `${Math.min(parseFloat(donePct), 100)}%`,
                        borderRadius: 99,
                        background: "linear-gradient(90deg, #8e5df7, #d6af62)",
                        transition: "width 0.6s ease",
                    }} />
                </div>
            </div>

            {/* Quick checkin */}
            {item.status === "open" && (
                <div className="glass-card" style={{ marginBottom: 20 }}>
                    <h3 style={{ marginBottom: 10 }}>Quick Check-in</h3>
                    <div className="action-row">
                        <button className="btn btn-success" onClick={() => handleCheckin("done")}>✅ Done</button>
                        <button className="btn btn-ghost" onClick={() => handleCheckin("partial")}>🔄 Partial</button>
                        <button className="btn btn-danger" onClick={() => handleCheckin("missed")}>❌ Missed</button>
                    </div>
                </div>
            )}

            {/* Info */}
            <div className="glass-card" style={{ marginBottom: 20 }}>
                <div style={{ display: "grid", gap: 8, fontSize: 13 }}>
                    <div><strong>Status:</strong> <span className={`badge badge-${item.status === "open" ? "active" : item.status === "done" ? "approved" : "rejected"}`}>{item.status}</span></div>
                    {item.start_date && <div><strong>Start Date:</strong> {item.start_date}</div>}
                    {item.due_at && <div><strong>Due:</strong> {new Date(item.due_at).toLocaleDateString()}</div>}
                    {item.notes && <div><strong>Notes:</strong> {item.notes}</div>}
                </div>
            </div>

            {/* Checkin History */}
            {data.checkins && data.checkins.length > 0 && (
                <div className="glass-card">
                    <h3 style={{ marginBottom: 12 }}>Check-in History</h3>
                    <div style={{ display: "grid", gap: 6 }}>
                        {data.checkins.map((c) => (
                            <div key={c.id} style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                padding: "8px 12px",
                                border: "1px solid var(--border-glass)",
                                borderRadius: 8,
                                fontSize: 13,
                            }}>
                                <span style={{
                                    color: c.result === "done" ? "var(--accent-gold)" : c.result === "missed" ? "var(--accent-red)" : "var(--text-secondary)",
                                    fontWeight: 600,
                                }}>
                                    {c.result === "done" ? "✅" : c.result === "missed" ? "❌" : "🔄"} {c.result}
                                </span>
                                <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
                                    {c.timestamp ? new Date(c.timestamp).toLocaleString() : "—"}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
