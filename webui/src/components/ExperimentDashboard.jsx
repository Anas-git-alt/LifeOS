import { useState, useEffect } from 'react';
import { getExperiments, getProviderTelemetry } from '../api';

const RISK_CONFIG = {
  low: { label: 'Low', cls: 'risk-chip risk-chip-low' },
  medium: { label: 'Medium', cls: 'risk-chip risk-chip-medium' },
  high: { label: 'High', cls: 'risk-chip risk-chip-high' },
};

function RiskChip({ level }) {
  const cfg = RISK_CONFIG[level] || RISK_CONFIG.low;
  return <span className={cfg.cls}>{cfg.label}</span>;
}

function ScoreBar({ score, label }) {
  const pct = Math.round(score * 100);
  return (
    <div className="score-bar-wrap">
      <div className="score-bar-track">
        <div
          className="score-bar-fill"
          style={{ width: `${pct}%` }}
          aria-label={`${label}: ${pct}%`}
        />
      </div>
      <span className="score-bar-label">{pct}%</span>
    </div>
  );
}

function ProviderTelemetry({ stats }) {
  if (!stats || stats.length === 0) return null;
  return (
    <div className="telemetry-grid">
      {stats.map((p) => (
        <div key={p.provider} className="telemetry-card">
          <div className="telemetry-card-header">
            <span className="telemetry-provider-name">{p.provider}</span>
            <span className={`status-dot ${p.circuit_open ? 'status-dot-danger' : 'status-dot-success'}`} />
          </div>
          <div className="telemetry-card-body">
            <div className="telemetry-row">
              <span>Avg latency</span>
              <strong>{p.avg_latency_ms != null ? `${p.avg_latency_ms}ms` : '—'}</strong>
            </div>
            <div className="telemetry-row">
              <span>Avg tokens</span>
              <strong>{p.avg_tokens ?? '—'}</strong>
            </div>
            <div className="telemetry-row">
              <span>✅ / ❌</span>
              <strong>{p.successes} / {p.failures}</strong>
            </div>
            {p.circuit_open && (
              <div className="telemetry-alert">⚠️ Circuit open</div>
            )}
          </div>
          {p.last_model && (
            <div className="telemetry-card-footer">
              Model: <code>{p.last_model.split('/').pop()}</code>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ExperimentDashboard() {
  const [experiments, setExperiments] = useState([]);
  const [pendingPromotions, setPendingPromotions] = useState([]);
  const [telemetry, setTelemetry] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function load() {
    setLoading(true);
    setError('');
    try {
      const [expData, telData] = await Promise.all([
        getExperiments(50),
        getProviderTelemetry(),
      ]);
      setExperiments(expData?.experiments || []);
      setPendingPromotions(expData?.pending_promotions || []);
      setTelemetry(telData?.providers || []);
    } catch (e) {
      setError('Could not load experiment data. Backend may be offline.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    return () => clearInterval(iv);
  }, []);

  const shadowWins = experiments.filter((e) => e.shadow_wins).length;
  const winRate = experiments.length > 0
    ? Math.round((shadowWins / experiments.length) * 100)
    : 0;
  const hasPendingPromotionRequest = pendingPromotions.length > 0;
  const pendingPromotionSummary = pendingPromotions.length === 1
    ? `Shadow provider "${pendingPromotions[0]}" hit the promotion threshold. Review the Approval Queue to decide whether to promote it.`
    : `${pendingPromotions.length} shadow providers hit the promotion threshold. Review the Approval Queue to decide whether to promote them.`;

  return (
    <div className="page-header" style={{ marginBottom: 0 }}>
      <div className="page-header-row" style={{ marginBottom: 20 }}>
        <div>
          <h1>🧪 Experiments</h1>
          <p style={{ marginTop: 4 }}>
            Shadow-router A/B test log. Watching alternative providers passively — promotion requests appear only after sustained wins and still need your approval.
          </p>
        </div>
        <button className="btn btn-ghost" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : '↺ Refresh'}
        </button>
      </div>

      {/* Provider Telemetry */}
      <div className="card" style={{ padding: '16px', marginBottom: 16 }}>
        <div className="panel-card-head">
          <h2>Live Provider Health</h2>
          <span>Updates every 30s</span>
        </div>
        {telemetry.length === 0 ? (
          <p className="empty-state" style={{ padding: '20px 0', textAlign: 'left' }}>
            No telemetry yet. Data appears after the first LLM call.
          </p>
        ) : (
          <ProviderTelemetry stats={telemetry} />
        )}
      </div>

      {/* Summary stats */}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="card" style={{ padding: '14px 16px' }}>
          <div className="stat-value">{experiments.length}</div>
          <div className="stat-label">Total runs</div>
        </div>
        <div className="card" style={{ padding: '14px 16px' }}>
          <div className="stat-value" style={{ color: 'var(--color-success)' }}>{shadowWins}</div>
          <div className="stat-label">Shadow wins</div>
        </div>
        <div className="card" style={{ padding: '14px 16px' }}>
          <div className="stat-value">{winRate}%</div>
          <div className="stat-label">Shadow win rate</div>
        </div>
      </div>

      {/* Promotion candidates banner */}
      {hasPendingPromotionRequest && (
        <div className="card experiment-promo-banner" style={{ marginBottom: 16 }}>
          <span className="experiment-promo-icon">🏆</span>
          <div>
            <strong>Promotion request pending</strong>
            <p>{pendingPromotionSummary}</p>
          </div>
        </div>
      )}

      {/* Error */}
      {error && <p className="status-message-error" style={{ marginBottom: 12 }}>{error}</p>}

      {/* Experiment table */}
      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        {loading && experiments.length === 0 ? (
          <div className="empty-state">Loading experiment data…</div>
        ) : experiments.length === 0 ? (
          <div className="empty-state" style={{ padding: 40 }}>
            <p>No shadow tests run yet.</p>
            <p style={{ marginTop: 8, fontSize: 12 }}>They fire automatically on ~5% of successful LLM calls when multiple healthy providers are configured.</p>
          </div>
        ) : (
          <table className="experiment-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Primary</th>
                <th>Shadow</th>
                <th>Primary score</th>
                <th>Shadow score</th>
                <th>Shadow latency</th>
                <th>Cost est.</th>
                <th>Winner</th>
              </tr>
            </thead>
            <tbody>
              {experiments.map((e) => (
                <tr key={e.id} className={e.shadow_wins ? 'experiment-row-shadow-wins' : ''}>
                  <td className="experiment-td-time">
                    {e.created_at ? new Date(e.created_at).toLocaleTimeString() : '—'}
                  </td>
                  <td><code>{e.primary_provider}</code></td>
                  <td><code>{e.shadow_provider}</code></td>
                  <td><ScoreBar score={e.primary_score} label="Primary" /></td>
                  <td><ScoreBar score={e.shadow_score} label="Shadow" /></td>
                  <td>{e.shadow_latency_ms ? `${Math.round(e.shadow_latency_ms)}ms` : '—'}</td>
                  <td>${(e.cost_estimate || 0).toFixed(5)}</td>
                  <td>
                    {e.shadow_wins
                      ? <span className="experiment-badge experiment-badge-shadow">Shadow 🏆</span>
                      : <span className="experiment-badge experiment-badge-primary">Primary</span>}
                    {e.promoted && <span className="experiment-badge experiment-badge-promoted">Promoted</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
