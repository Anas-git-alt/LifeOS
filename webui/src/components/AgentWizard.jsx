import { useState } from "react";
import { createAgent, proposeAgent } from "../api";

const DEFAULT_FORM = {
  name: "",
  purpose: "",
  discord_channel: "",
  cadence: "0 8 *",
  approval_policy: "auto",
  provider: "openrouter",
  model: "openrouter/auto",
};

export default function AgentWizard() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [queueForApproval, setQueueForApproval] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    const payload = {
      name: form.name.trim(),
      description: form.purpose.trim(),
      system_prompt: `You are ${form.name.trim()}. Purpose: ${form.purpose.trim()}`,
      provider: form.provider,
      model: form.model,
      discord_channel: form.discord_channel.replace(/^#/, "").trim(),
      cadence: form.cadence.trim(),
      enabled: true,
      config_json: { approval_policy: form.approval_policy },
    };
    try {
      if (queueForApproval) {
        const result = await proposeAgent(`Create agent '${payload.name}'`, payload);
        setSuccess(`Agent proposal queued as PendingAction #${result.pending_action_id}.`);
      } else {
        await createAgent(payload);
        setSuccess("Agent created.");
      }
      setForm(DEFAULT_FORM);
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="glass-card">
      <div className="page-header">
        <h2>Create Agent</h2>
        <p>Spawn a new agent from WebUI. Missing required fields are blocked before submission.</p>
      </div>
      <form onSubmit={submit}>
        <div className="grid grid-2">
          <div className="form-group">
            <label>Agent Name</label>
            <input value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} required />
          </div>
          <div className="form-group">
            <label>Discord Channel</label>
            <input
              value={form.discord_channel}
              onChange={(e) => setForm((prev) => ({ ...prev, discord_channel: e.target.value }))}
              placeholder="#planning"
              required
            />
          </div>
          <div className="form-group">
            <label>Purpose</label>
            <input
              value={form.purpose}
              onChange={(e) => setForm((prev) => ({ ...prev, purpose: e.target.value }))}
              required
            />
          </div>
          <div className="form-group">
            <label>Cadence</label>
            <input
              value={form.cadence}
              onChange={(e) => setForm((prev) => ({ ...prev, cadence: e.target.value }))}
              placeholder="0 8 *"
              required
            />
          </div>
          <div className="form-group">
            <label>Provider</label>
            <input
              value={form.provider}
              onChange={(e) => setForm((prev) => ({ ...prev, provider: e.target.value }))}
              required
            />
          </div>
          <div className="form-group">
            <label>Model</label>
            <input value={form.model} onChange={(e) => setForm((prev) => ({ ...prev, model: e.target.value }))} required />
          </div>
          <div className="form-group">
            <label>Approval Policy</label>
            <select
              value={form.approval_policy}
              onChange={(e) => setForm((prev) => ({ ...prev, approval_policy: e.target.value }))}
            >
              <option value="auto">auto</option>
              <option value="always">always</option>
              <option value="never">never</option>
            </select>
          </div>
        </div>
        <label className="checkbox-row">
          <input type="checkbox" checked={queueForApproval} onChange={(e) => setQueueForApproval(e.target.checked)} />
          Queue in approval flow (recommended)
        </label>
        <div className="action-row">
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? "Submitting..." : queueForApproval ? "Create via Approval Queue" : "Create Agent Directly"}
          </button>
        </div>
      </form>
      {error && <p style={{ color: "#f87171", marginTop: 10 }}>{error}</p>}
      {success && <p style={{ color: "#86efac", marginTop: 10 }}>{success}</p>}
    </section>
  );
}
