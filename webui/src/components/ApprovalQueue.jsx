import { useState, useEffect } from 'react'
import { getPendingActions, getAllActions, decideAction } from '../api'

export default function ApprovalQueue() {
    const [actions, setActions] = useState([])
    const [view, setView] = useState('pending') // pending | all
    const [loading, setLoading] = useState(true)

    useEffect(() => { loadActions() }, [view])

    async function loadActions() {
        setLoading(true)
        try {
            const data = view === 'pending' ? await getPendingActions() : await getAllActions()
            setActions(data)
        } catch (e) {
            console.error('Failed to load actions:', e)
        } finally {
            setLoading(false)
        }
    }

    async function handleDecide(id, approved) {
        try {
            await decideAction(id, approved)
            loadActions()
        } catch (e) {
            alert(`Error: ${e.message}`)
        }
    }

    return (
        <div>
            <header className="page-header">
                <h1>✅ Approval Queue</h1>
                <p>Review and approve/reject agent-proposed actions</p>
            </header>

            <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
                <button className={`btn ${view === 'pending' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setView('pending')}>
                    ⏳ Pending
                </button>
                <button className={`btn ${view === 'all' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setView('all')}>
                    📋 All Actions
                </button>
                <button className="btn btn-ghost" onClick={loadActions} style={{ marginLeft: 'auto' }}>
                    🔄 Refresh
                </button>
            </div>

            {loading ? (
                <div className="empty-state"><div className="emoji">⏳</div>Loading...</div>
            ) : actions.length === 0 ? (
                <div className="empty-state">
                    <div className="emoji">✨</div>
                    <p>{view === 'pending' ? 'No pending approvals — all clear!' : 'No actions recorded yet.'}</p>
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {actions.map(action => (
                        <div key={action.id} className="glass-card">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: 8 }}>
                                <div>
                                    <span style={{ fontWeight: 600, fontSize: 15 }}>
                                        #{action.id} · {action.agent_name}
                                    </span>
                                    <span className={`badge badge-${action.status}`} style={{ marginLeft: 8 }}>
                                        {action.status}
                                    </span>
                                </div>
                                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                    {new Date(action.created_at).toLocaleString()}
                                </span>
                            </div>

                            <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginBottom: 8 }}>
                                {action.summary}
                            </p>

                            {action.details && action.details !== action.summary && (
                                <details style={{ marginBottom: 8 }}>
                                    <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 13 }}>
                                        View full details
                                    </summary>
                                    <pre style={{
                                        marginTop: 8,
                                        padding: 12,
                                        background: 'var(--bg-secondary)',
                                        borderRadius: 8,
                                        fontSize: 13,
                                        whiteSpace: 'pre-wrap',
                                        color: 'var(--text-secondary)',
                                        maxHeight: 200,
                                        overflow: 'auto',
                                    }}>
                                        {action.details}
                                    </pre>
                                </details>
                            )}

                            {action.status === 'pending' && (
                                <div className="action-row">
                                    <button className="btn btn-success" onClick={() => handleDecide(action.id, true)}>
                                        ✅ Approve
                                    </button>
                                    <button className="btn btn-danger" onClick={() => handleDecide(action.id, false)}>
                                        ❌ Reject
                                    </button>
                                </div>
                            )}

                            {action.result && (
                                <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-muted)' }}>
                                    Result: {action.result}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
