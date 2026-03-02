import { useState, useEffect } from 'react'
import { getAgent, updateAgent, getProviders } from '../api'

export default function AgentConfig({ agentName, onBack }) {
    const [agent, setAgent] = useState(null)
    const [providers, setProviders] = useState([])
    const [form, setForm] = useState({})
    const [saving, setSaving] = useState(false)
    const [message, setMessage] = useState('')

    useEffect(() => {
        if (agentName) loadAgent()
        loadProviders()
    }, [agentName])

    async function loadAgent() {
        try {
            const a = await getAgent(agentName)
            setAgent(a)
            setForm({
                description: a.description || '',
                system_prompt: a.system_prompt || '',
                provider: a.provider || 'openrouter',
                model: a.model || '',
                fallback_provider: a.fallback_provider || '',
                fallback_model: a.fallback_model || '',
                discord_channel: a.discord_channel || '',
                cadence: a.cadence || '',
                enabled: a.enabled,
            })
        } catch (e) {
            setMessage(`Error: ${e.message}`)
        }
    }

    async function loadProviders() {
        try { setProviders(await getProviders()) } catch (e) { /* ignore */ }
    }

    async function handleSave() {
        setSaving(true)
        setMessage('')
        try {
            await updateAgent(agentName, form)
            setMessage('✅ Agent updated successfully!')
        } catch (e) {
            setMessage(`❌ Error: ${e.message}`)
        } finally {
            setSaving(false)
        }
    }

    if (!agent) return <div className="empty-state"><div className="emoji">⏳</div>Loading...</div>

    return (
        <div>
            <header className="page-header">
                <button className="btn btn-ghost" onClick={onBack} style={{ marginBottom: 16 }}>
                    ← Back to Agents
                </button>
                <h1>⚙️ {agentName}</h1>
                <p>Edit agent configuration, model, provider, and schedule</p>
            </header>

            <div className="glass-card" style={{ maxWidth: 700 }}>
                {message && <div style={{ marginBottom: 16, padding: '10px 16px', borderRadius: 8, background: message.startsWith('✅') ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)' }}>{message}</div>}

                <div className="form-group">
                    <label>Description</label>
                    <input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
                </div>

                <div className="form-group">
                    <label>System Prompt</label>
                    <textarea rows={6} value={form.system_prompt} onChange={e => setForm({ ...form, system_prompt: e.target.value })} />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="form-group">
                        <label>Provider</label>
                        <select value={form.provider} onChange={e => setForm({ ...form, provider: e.target.value })}>
                            {providers.map(p => (
                                <option key={p.name} value={p.name}>
                                    {p.name.toUpperCase()} {p.available ? '✅' : '❌'}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <label>Model</label>
                        <input value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} placeholder="e.g. openrouter/auto" />
                    </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="form-group">
                        <label>Fallback Provider</label>
                        <select value={form.fallback_provider} onChange={e => setForm({ ...form, fallback_provider: e.target.value })}>
                            <option value="">None</option>
                            {providers.map(p => (
                                <option key={p.name} value={p.name}>{p.name.toUpperCase()}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <label>Fallback Model</label>
                        <input value={form.fallback_model} onChange={e => setForm({ ...form, fallback_model: e.target.value })} placeholder="Optional" />
                    </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div className="form-group">
                        <label>Discord Channel</label>
                        <input value={form.discord_channel} onChange={e => setForm({ ...form, discord_channel: e.target.value })} placeholder="e.g. prayer-tracker" />
                    </div>
                    <div className="form-group">
                        <label>Schedule (cron: min hour dow)</label>
                        <input value={form.cadence} onChange={e => setForm({ ...form, cadence: e.target.value })} placeholder="e.g. 0 8 *" />
                    </div>
                </div>

                <div className="form-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                        <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} style={{ width: 'auto' }} />
                        Enabled
                    </label>
                </div>

                <div className="action-row">
                    <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                        {saving ? '⏳ Saving...' : '💾 Save Changes'}
                    </button>
                    <button className="btn btn-ghost" onClick={onBack}>Cancel</button>
                </div>
            </div>
        </div>
    )
}
