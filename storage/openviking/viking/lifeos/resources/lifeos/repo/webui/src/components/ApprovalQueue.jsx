import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPendingActions, getAllActions, decideAction } from '../api'

export default function ApprovalQueue() {
    const [view, setView] = useState('pending') // pending | all
    const [deciding, setDeciding] = useState(null) // action id being decided
    const [decideError, setDecideError] = useState('')
    const queryClient = useQueryClient()

    const queryKey = ['approvals', view]
    const { data: actions = [], isLoading } = useQuery({
        queryKey,
        queryFn: () => view === 'pending' ? getPendingActions() : getAllActions(),
        refetchInterval: 15_000,
    })

    async function handleDecide(id, approved) {
        setDeciding(id)
        setDecideError('')
        try {
            await decideAction(id, approved)
            queryClient.invalidateQueries({ queryKey: ['approvals'] })
        } catch (e) {
            setDecideError(`Action #${id} failed: ${e.message}`)
        } finally {
            setDeciding(null)
        }
    }

    return (
        <div>
            <header className="page-header">
                <h1>✅ Approval Queue</h1>
                <p>Review and approve/reject agent-proposed actions</p>
            </header>

            <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
                <button
                    className={`btn ${view === 'pending' ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => setView('pending')}
                >
                    ⏳ Pending
                </button>
                <button
                    className={`btn ${view === 'all' ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => setView('all')}
                >
                    📋 All Actions
                </button>
                <button
                    className="btn btn-ghost"
                    onClick={() => queryClient.invalidateQueries({ queryKey: ['approvals'] })}
                    style={{ marginLeft: 'auto' }}
                >
                    🔄 Refresh
                </button>
            </div>

            {decideError && <div className="approval-error glass-card" style={{ marginBottom: 12 }}>{decideError}</div>}

            {isLoading ? (
                <div className="widget-skeleton">
                    {[1, 2, 3].map(i => (
                        <div key={i} className="glass-card" style={{ padding: 16 }}>
                            <div className="widget-skeleton-line" style={{ width: '40%', marginBottom: 10 }} />
                            <div className="widget-skeleton-line" style={{ width: '80%', marginBottom: 8 }} />
                            <div className="widget-skeleton-line" style={{ width: '60%' }} />
                        </div>
                    ))}
                </div>
            ) : actions.length === 0 ? (
                <div className="empty-state">
                    <div className="emoji">✨</div>
                    <p>{view === 'pending' ? 'No pending approvals — all clear!' : 'No actions recorded yet.'}</p>
                </div>
            ) : (
                <div className="approval-list">
                    {actions.map(action => (
                        <div key={action.id} className="glass-card">
                            <div className="approval-card-head">
                                <div>
                                    <span className="approval-card-id">
                                        #{action.id} · {action.agent_name}
                                    </span>
                                    <span className={`badge badge-${action.status}`} style={{ marginLeft: 8 }}>
                                        {action.status}
                                    </span>
                                </div>
                                <span className="approval-card-timestamp">
                                    {new Date(action.created_at).toLocaleString()}
                                </span>
                            </div>

                            <p className="approval-card-body">{action.summary}</p>

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
                                    <button
                                        className="btn btn-success"
                                        disabled={deciding === action.id}
                                        onClick={() => handleDecide(action.id, true)}
                                    >
                                        ✅ Approve
                                    </button>
                                    <button
                                        className="btn btn-danger"
                                        disabled={deciding === action.id}
                                        onClick={() => handleDecide(action.id, false)}
                                    >
                                        ❌ Reject
                                    </button>
                                    {deciding === action.id && (
                                        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Saving…</span>
                                    )}
                                </div>
                            )}

                            {action.result && (
                                <div className="approval-card-result">Result: {action.result}</div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
