import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api";

export default function GlobalSettings() {
  const [form, setForm] = useState({
    data_start_date: "",
    default_timezone: "Africa/Casablanca",
    autonomy_enabled: true,
    approval_required_for_mutations: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const payload = await getSettings();
        if (!active) return;
        setForm({
          data_start_date: payload.data_start_date || "2026-03-02",
          default_timezone: payload.default_timezone || "Africa/Casablanca",
          autonomy_enabled: Boolean(payload.autonomy_enabled),
          approval_required_for_mutations: Boolean(payload.approval_required_for_mutations),
        });
      } catch (exc) {
        if (!active) return;
        setError(String(exc.message || exc));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const onSave = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const payload = await updateSettings(form);
      setForm({
        data_start_date: payload.data_start_date,
        default_timezone: payload.default_timezone,
        autonomy_enabled: payload.autonomy_enabled,
        approval_required_for_mutations: payload.approval_required_for_mutations,
      });
      setSuccess("Settings saved.");
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="glass-card">Loading settings...</div>;
  }

  return (
    <section className="glass-card">
      <div className="page-header">
        <h2>Global Settings</h2>
        <p>
          Data start date is inclusive. Analytics and retrospective reports ignore data older than this date. Default
          fallback is <strong>2026-03-02</strong> (Africa/Casablanca) if first-run date cannot be resolved.
        </p>
      </div>
      <form onSubmit={onSave}>
        <div className="grid grid-2">
          <div className="form-group">
            <label htmlFor="data-start-date">Data Start Date</label>
            <input
              id="data-start-date"
              type="date"
              value={form.data_start_date}
              onChange={(event) => setForm((prev) => ({ ...prev, data_start_date: event.target.value }))}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="default-timezone">Default Timezone</label>
            <input
              id="default-timezone"
              type="text"
              value={form.default_timezone}
              onChange={(event) => setForm((prev) => ({ ...prev, default_timezone: event.target.value }))}
              required
            />
          </div>
        </div>
        <div className="grid">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.autonomy_enabled}
              onChange={(event) => setForm((prev) => ({ ...prev, autonomy_enabled: event.target.checked }))}
            />
            Enable proactive autonomy features
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.approval_required_for_mutations}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, approval_required_for_mutations: event.target.checked }))
              }
            />
            Require approvals for schedule/data mutations
          </label>
        </div>
        <div className="action-row">
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </div>
        {error && <p className="status-message status-message-error">{error}</p>}
        {success && <p className="status-message status-message-success">{success}</p>}
      </form>
    </section>
  );
}
