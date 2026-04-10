import { useEffect, useState } from "react";
import { getQuranProgress, logQuranReading, resetQuranProgress } from "../api";

export default function QuranLog() {
    const [progress, setProgress] = useState(null);
    const [endPage, setEndPage] = useState("");
    const [startPage, setStartPage] = useState("");
    const [note, setNote] = useState("");
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        load();
    }, []);

    async function load() {
        try {
            const data = await getQuranProgress();
            setProgress(data);
            setError("");
        } catch (err) {
            setError(err.message);
        }
    }

    async function handleLog() {
        if (!endPage) return;
        setLoading(true);
        setSuccess("");
        setError("");
        try {
            const result = await logQuranReading(
                parseInt(endPage),
                startPage ? parseInt(startPage) : null,
                note || null
            );
            setSuccess(`Logged pages ${result.start_page}–${result.end_page} (${result.pages_read} pages)`);
            setEndPage("");
            setStartPage("");
            setNote("");
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    async function handleReset() {
        if (!window.confirm("Reset Quran reading progress and move the bookmark back to page 1?")) return;
        setLoading(true);
        setSuccess("");
        setError("");
        try {
            const result = await resetQuranProgress();
            setProgress(result);
            setEndPage("");
            setStartPage("");
            setNote("");
            setSuccess("Quran progress reset. The bookmark is back on page 1.");
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    const completionPct = progress?.completion_pct || 0;
    const currentPage = progress?.current_page || 1;
    const totalRead = progress?.pages_read_total || 0;

    return (
        <div>
            <header className="page-header">
                <h1>📖 Quran Reading Log</h1>
                <p>Page-based tracking with auto-resume bookmark.</p>
            </header>
            {error && <div className="glass-card status-message-error" style={{ marginBottom: 16 }}>{error}</div>}
            {success && <div className="glass-card status-message-success" style={{ marginBottom: 16 }}>{success}</div>}

            {/* Bookmark & Progress */}
            <div className="grid grid-3" style={{ marginBottom: 20 }}>
                <div className="glass-card">
                    <div className="stat-value status-text-success">{currentPage}</div>
                    <div className="stat-label">Current Bookmark (next start)</div>
                </div>
                <div className="glass-card">
                    <div className="stat-value">{totalRead}</div>
                    <div className="stat-label">Total Pages Read</div>
                </div>
                <div className="glass-card">
                    <div className="stat-value">{completionPct}%</div>
                    <div className="stat-label">Khatma Progress</div>
                </div>
            </div>

            {/* Progress Bar */}
            <div className="glass-card" style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 13, color: "var(--text-secondary)" }}>
                    <span>Page {currentPage} of 604</span>
                    <span>{completionPct}% complete</span>
                </div>
                <div style={{
                    height: 12,
                    borderRadius: 99,
                    background: "rgba(255,255,255,0.06)",
                    overflow: "hidden",
                    border: "1px solid var(--border-glass)",
                }}>
                    <div style={{
                        height: "100%",
                        width: `${Math.min(completionPct, 100)}%`,
                        borderRadius: 99,
                        background: "linear-gradient(90deg, #8e5df7, #d6af62)",
                        transition: "width 0.6s ease",
                    }} />
                </div>
            </div>

            {/* Log Form */}
            <div className="glass-card" style={{ marginBottom: 20 }}>
                <h3 style={{ marginBottom: 12 }}>Log Reading Session</h3>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
                    <div>
                        <label>Start Page (auto: {currentPage})</label>
                        <input
                            type="number"
                            min="1"
                            max="604"
                            value={startPage}
                            onChange={(e) => setStartPage(e.target.value)}
                            placeholder={`${currentPage} (auto)`}
                        />
                    </div>
                    <div>
                        <label>End Page *</label>
                        <input
                            type="number"
                            min="1"
                            max="604"
                            value={endPage}
                            onChange={(e) => setEndPage(e.target.value)}
                            placeholder="e.g. 25"
                        />
                    </div>
                </div>
                <div style={{ marginBottom: 10 }}>
                    <label>Note (optional)</label>
                    <input
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="e.g. Surat Al-Baqara review"
                    />
                </div>
                <button className="btn btn-primary" onClick={handleLog} disabled={loading || !endPage}>
                    {loading ? "Logging..." : "Log Reading"}
                </button>
            </div>

            <div className="glass-card" style={{ marginBottom: 20 }}>
                <div className="agent-card-header" style={{ marginBottom: 12 }}>
                    <div>
                        <h3 style={{ margin: 0 }}>Start Over</h3>
                        <p style={{ marginTop: 6, color: "var(--text-secondary)", fontSize: 13 }}>
                            Clear the reading log and reset the bookmark back to page 1.
                        </p>
                    </div>
                </div>
                <button className="btn btn-danger" onClick={handleReset} disabled={loading}>
                    {loading ? "Resetting..." : "Reset Progress"}
                </button>
            </div>

            {/* Recent Readings */}
            {progress && progress.recent_readings && progress.recent_readings.length > 0 && (
                <div className="glass-card">
                    <h3 style={{ marginBottom: 12 }}>Recent Readings</h3>
                    <div style={{ display: "grid", gap: 8 }}>
                        {progress.recent_readings.map((r) => (
                            <div key={r.id} style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                padding: "10px 14px",
                                border: "1px solid var(--border-glass)",
                                borderRadius: 10,
                                background: "rgba(255,255,255,0.02)",
                            }}>
                                <div>
                                    <span style={{ fontWeight: 600 }}>Pages {r.start_page}–{r.end_page}</span>
                                    <span style={{ color: "var(--text-secondary)", fontSize: 12, marginLeft: 8 }}>
                                        ({r.pages_read} pages)
                                    </span>
                                </div>
                                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                    {r.note && <span style={{ color: "var(--text-muted)", fontSize: 12 }}>{r.note}</span>}
                                    <span className="meta-tag">{r.local_date}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
