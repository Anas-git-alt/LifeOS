import { useEffect, useMemo, useState } from "react";
import {
  createJob,
  deleteJob,
  getAgents,
  getJobRuns,
  getJobs,
  pauseJob,
  resumeJob,
  updateJob,
} from "../api";

const DEFAULT_JOB = {
  name: "",
  description: "",
  agent_name: "",
  cron_expression: "30 7 mon-fri",
  timezone: "Africa/Casablanca",
  target_channel: "",
  prompt_template: "",
  enabled: true,
  approval_required: true,
};

export default function JobsManager() {
  const [jobs, setJobs] = useState([]);
  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [form, setForm] = useState(DEFAULT_JOB);
  const [editingJobId, setEditingJobId] = useState(null);
  const [runsByJob, setRunsByJob] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const loadData = async (agentName = selectedAgent) => {
    setLoading(true);
    setError("");
    try {
      const [jobRows, agentRows] = await Promise.all([getJobs(agentName), getAgents()]);
      setJobs(jobRows);
      setAgents(agentRows);
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedJob = useMemo(() => jobs.find((row) => row.id === editingJobId) || null, [jobs, editingJobId]);

  useEffect(() => {
    if (!selectedJob) return;
    setForm({
      name: selectedJob.name || "",
      description: selectedJob.description || "",
      agent_name: selectedJob.agent_name || "",
      cron_expression: selectedJob.cron_expression || "",
      timezone: selectedJob.timezone || "Africa/Casablanca",
      target_channel: selectedJob.target_channel || "",
      prompt_template: selectedJob.prompt_template || "",
      enabled: Boolean(selectedJob.enabled),
      approval_required: Boolean(selectedJob.approval_required),
    });
  }, [selectedJob]);

  const resetForm = () => {
    setForm(DEFAULT_JOB);
    setEditingJobId(null);
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = {
        ...form,
        agent_name: form.agent_name || null,
        target_channel: form.target_channel || null,
        prompt_template: form.prompt_template || null,
        source: editingJobId ? "webui_edit" : "webui_create",
        created_by: "webui",
      };
      if (editingJobId) {
        await updateJob(editingJobId, payload);
      } else {
        await createJob(payload);
      }
      await loadData(selectedAgent);
      resetForm();
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setSaving(false);
    }
  };

  const togglePaused = async (job) => {
    try {
      if (job.paused) await resumeJob(job.id);
      else await pauseJob(job.id);
      await loadData(selectedAgent);
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  };

  const removeJob = async (job) => {
    try {
      await deleteJob(job.id);
      await loadData(selectedAgent);
      if (editingJobId === job.id) resetForm();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  };

  const loadRuns = async (jobId) => {
    try {
      const rows = await getJobRuns(jobId, 10);
      setRunsByJob((prev) => ({ ...prev, [jobId]: rows }));
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  };

  const getJobStatusMeta = (job) => {
    if (job.paused) return { label: "paused", badge: "badge-pending" };
    if (job.enabled) return { label: "active", badge: "badge-active" };
    return { label: "disabled", badge: "badge-rejected" };
  };

  return (
    <section className="glass-card">
      <div className="page-header">
        <h2>Cron Jobs</h2>
        <p>Create, edit, pause, resume, and delete timezone-aware jobs globally or per agent.</p>
      </div>

      <div className="form-group">
        <label htmlFor="jobs-filter-agent">Filter by agent</label>
        <select
          id="jobs-filter-agent"
          value={selectedAgent}
          onChange={async (event) => {
            const value = event.target.value;
            setSelectedAgent(value);
            await loadData(value);
          }}
        >
          <option value="">All agents</option>
          {agents.map((agent) => (
            <option key={agent.name} value={agent.name}>
              {agent.name}
            </option>
          ))}
        </select>
      </div>

      <form onSubmit={onSubmit}>
        <div className="grid grid-2">
          <div className="form-group">
            <label htmlFor="job-name">Job Name</label>
            <input id="job-name" value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} required />
          </div>
          <div className="form-group">
            <label htmlFor="job-description">Description</label>
            <input
              id="job-description"
              value={form.description}
              onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="What this job is for and expected outcome."
            />
          </div>
          <div className="form-group">
            <label htmlFor="job-agent">Agent</label>
            <select
              id="job-agent"
              value={form.agent_name}
              onChange={(e) => setForm((prev) => ({ ...prev, agent_name: e.target.value }))}
              required
            >
              <option value="">Select agent</option>
              {agents.map((agent) => (
                <option key={agent.name} value={agent.name}>
                  {agent.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="job-cron">Cron</label>
            <input
              id="job-cron"
              value={form.cron_expression}
              onChange={(e) => setForm((prev) => ({ ...prev, cron_expression: e.target.value }))}
              placeholder="30 7 mon-fri or 30 7 * * mon-fri"
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="job-timezone">Timezone</label>
            <input
              id="job-timezone"
              value={form.timezone}
              onChange={(e) => setForm((prev) => ({ ...prev, timezone: e.target.value }))}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="job-target-channel">Target Channel</label>
            <input
              id="job-target-channel"
              value={form.target_channel}
              onChange={(e) => setForm((prev) => ({ ...prev, target_channel: e.target.value.replace(/^#/, "") }))}
              placeholder="fitness-log"
            />
          </div>
          <div className="form-group">
            <label htmlFor="job-prompt-template">Prompt Template</label>
            <input
              id="job-prompt-template"
              value={form.prompt_template}
              onChange={(e) => setForm((prev) => ({ ...prev, prompt_template: e.target.value }))}
              placeholder="Run your scheduled check-in now."
            />
          </div>
        </div>
        <div className="grid">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm((prev) => ({ ...prev, enabled: e.target.checked }))}
            />
            Enabled
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.approval_required}
              onChange={(e) => setForm((prev) => ({ ...prev, approval_required: e.target.checked }))}
            />
            Approval required
          </label>
        </div>
        <div className="action-row">
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? "Saving..." : editingJobId ? "Update Job" : "Create Job"}
          </button>
          {editingJobId && (
            <button className="btn btn-ghost" type="button" onClick={resetForm}>
              Cancel Edit
            </button>
          )}
        </div>
      </form>

      {error && <p className="error-text" style={{ marginTop: 12 }}>{error}</p>}
      {loading ? (
        <p style={{ marginTop: 14 }}>Loading jobs...</p>
      ) : (
        <div style={{ marginTop: 16 }}>
          {jobs.length === 0 ? (
            <p>No jobs found.</p>
          ) : (
            <div className="grid">
              {jobs.map((job) => {
                const status = getJobStatusMeta(job);
                return (
                <article key={job.id} className="glass-card job-card">
                  <div className="job-card-head">
                    <div className="job-card-summary">
                      <h3>
                        #{job.id} {job.name}
                      </h3>
                      <p className="job-card-meta">
                        Agent: <strong>{job.agent_name || "n/a"}</strong> · Cron: <code>{job.cron_expression}</code> · TZ:{" "}
                        <strong>{job.timezone}</strong>
                      </p>
                      {job.description && <p className="job-card-meta">Description: {job.description}</p>}
                      <p className="job-card-meta">
                        Last run: {job.last_run_at || "never"} · Next run: {job.next_run_at || "n/a"} · Status:{" "}
                        <span className={`badge ${status.badge}`}>{status.label}</span>
                      </p>
                      {job.last_error && <p className="error-text job-card-meta">Last error: {job.last_error}</p>}
                    </div>
                    <div className="job-card-actions">
                      <button className="btn btn-ghost" onClick={() => setEditingJobId(job.id)}>
                        Edit
                      </button>
                      <button className="btn btn-ghost" onClick={() => togglePaused(job)}>
                        {job.paused ? "Resume" : "Pause"}
                      </button>
                      <button className="btn btn-danger" onClick={() => removeJob(job)}>
                        Delete
                      </button>
                      <button className="btn btn-ghost" onClick={() => loadRuns(job.id)}>
                        Logs
                      </button>
                    </div>
                  </div>
                  {runsByJob[job.id] && (
                    <div style={{ marginTop: 10 }}>
                      <strong>Recent Runs</strong>
                      <ul className="run-log-list">
                        {runsByJob[job.id].map((run) => (
                          <li key={run.id}>
                            {run.created_at} · <span className={`badge ${run.status === "success" ? "badge-approved" : run.status === "running" ? "badge-pending" : "badge-rejected"}`}>{run.status}</span>
                            {run.error ? ` · ${run.error}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </article>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
