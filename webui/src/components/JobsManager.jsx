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
import { getJobRunDetail, getJobRunDetailLabel } from "../jobRuns";

const DEFAULT_JOB = {
  name: "",
  description: "",
  agent_name: "",
  schedule_type: "cron",
  cron_expression: "30 7 mon-fri",
  run_at: "",
  timezone: "Africa/Casablanca",
  notification_mode: "channel",
  target_channel_ref: "",
  prompt_template: "",
  enabled: true,
  approval_required: true,
  expect_reply: false,
  follow_up_after_minutes: 120,
};

function parseApiDate(value) {
  if (!value) return null;
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatInTimezone(value, timezone, fallback = "n/a") {
  const parsed = parseApiDate(value);
  if (!parsed) return value || fallback;
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone || "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function toDateTimeLocalValue(value, timezone) {
  const parsed = parseApiDate(value);
  if (!parsed) return "";
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: timezone || "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(parsed);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}T${byType.hour}:${byType.minute}`;
}

function parseChannelRef(value) {
  const raw = String(value || "").trim();
  if (!raw) return { target_channel: null, target_channel_id: null };
  const mentionMatch = raw.match(/^<#(\d+)>$/);
  if (mentionMatch) {
    return { target_channel: null, target_channel_id: mentionMatch[1] };
  }
  const digitsMatch = raw.match(/^(\d{6,})$/);
  if (digitsMatch) {
    return { target_channel: null, target_channel_id: digitsMatch[1] };
  }
  return { target_channel: raw.replace(/^#/, ""), target_channel_id: null };
}

function jobChannelRef(job) {
  if (job?.target_channel_id) return `<#${job.target_channel_id}>`;
  return job?.target_channel || "";
}

function jobStatusMeta(job) {
  if (job.schedule_type === "once" && job.completed_at) {
    if (job.last_status === "missed") return { label: "missed", badge: "badge-rejected" };
    return { label: "completed", badge: "badge-approved" };
  }
  if (job.paused) return { label: "paused", badge: "badge-pending" };
  if (job.enabled) return { label: "active", badge: "badge-active" };
  return { label: "disabled", badge: "badge-rejected" };
}

function jobScheduleText(job) {
  if (job.schedule_type === "once") {
    return `Once at ${formatInTimezone(job.run_at, job.timezone)}`;
  }
  return `Cron ${job.cron_expression}`;
}

function jobNotifyText(job) {
  if (job.notification_mode === "silent") return "silent/background";
  if (job.target_channel_id) return `<#${job.target_channel_id}>`;
  if (job.target_channel) return `#${job.target_channel}`;
  return "mapped channel";
}

function runStatusBadge(status) {
  if (["completed", "delivered"].includes(status)) return "badge-approved";
  if (["running", "pending_approval"].includes(status)) return "badge-pending";
  return "badge-rejected";
}

function runReplyStateText(run, job) {
  if (!job?.expect_reply || !run) return "";
  const replyCount = Number(run.reply_count || 0);
  if (replyCount > 0) return `${replyCount} repl${replyCount === 1 ? "y" : "ies"} received`;
  if (run.no_reply_follow_up_sent_at) {
    return `follow-up sent ${formatInTimezone(run.no_reply_follow_up_sent_at, job.timezone)}`;
  }
  if (run.awaiting_reply_until) {
    return `awaiting reply until ${formatInTimezone(run.awaiting_reply_until, job.timezone)}`;
  }
  return "awaiting reply";
}

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

  const loadLatestRuns = async (jobRows, limit = 1) => {
    const runs = await Promise.all(
      jobRows.map(async (job) => {
        try {
          return [job.id, await getJobRuns(job.id, limit)];
        } catch {
          return [job.id, []];
        }
      }),
    );
    return Object.fromEntries(runs);
  };

  const loadData = async (agentName = selectedAgent) => {
    setLoading(true);
    setError("");
    try {
      const [jobRows, agentRows] = await Promise.all([getJobs(agentName), getAgents()]);
      const latestRuns = await loadLatestRuns(jobRows, 1);
      setJobs(jobRows);
      setAgents(agentRows);
      setRunsByJob(latestRuns);
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
      schedule_type: selectedJob.schedule_type || "cron",
      cron_expression: selectedJob.cron_expression || "",
      run_at: toDateTimeLocalValue(selectedJob.run_at, selectedJob.timezone || "Africa/Casablanca"),
      timezone: selectedJob.timezone || "Africa/Casablanca",
      notification_mode:
        selectedJob.notification_mode || (selectedJob.target_channel || selectedJob.target_channel_id ? "channel" : "silent"),
      target_channel_ref: jobChannelRef(selectedJob),
      prompt_template: selectedJob.prompt_template || "",
      enabled: Boolean(selectedJob.enabled),
      approval_required: Boolean(selectedJob.approval_required),
      expect_reply: Boolean(selectedJob.expect_reply),
      follow_up_after_minutes: selectedJob.follow_up_after_minutes || 120,
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
      const channelData =
        form.notification_mode === "channel"
          ? parseChannelRef(form.target_channel_ref)
          : { target_channel: null, target_channel_id: null };
      const payload = {
        name: form.name,
        description: form.description || null,
        agent_name: form.agent_name || null,
        schedule_type: form.schedule_type,
        cron_expression: form.schedule_type === "cron" ? form.cron_expression || null : null,
        run_at: form.schedule_type === "once" && form.run_at ? `${form.run_at}:00` : null,
        timezone: form.timezone,
        notification_mode: form.notification_mode,
        ...channelData,
        prompt_template: form.prompt_template || null,
        enabled: form.enabled,
        approval_required: form.approval_required,
        expect_reply: form.expect_reply,
        follow_up_after_minutes: form.expect_reply ? Number(form.follow_up_after_minutes || 120) : null,
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

  return (
    <section className="glass-card">
      <div className="page-header">
        <h2>Scheduled Jobs</h2>
        <p>Create, edit, pause, resume, and inspect recurring or one-time jobs.</p>
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
            <label htmlFor="job-schedule-type">Schedule Type</label>
            <select
              id="job-schedule-type"
              value={form.schedule_type}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  schedule_type: e.target.value,
                  cron_expression: e.target.value === "cron" ? prev.cron_expression || "30 7 mon-fri" : "",
                  run_at: e.target.value === "once" ? prev.run_at : "",
                }))
              }
            >
              <option value="cron">Recurring</option>
              <option value="once">One-time</option>
            </select>
          </div>
          {form.schedule_type === "cron" ? (
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
          ) : (
            <div className="form-group">
              <label htmlFor="job-run-at">Run At</label>
              <input
                id="job-run-at"
                type="datetime-local"
                value={form.run_at}
                onChange={(e) => setForm((prev) => ({ ...prev, run_at: e.target.value }))}
                required
              />
            </div>
          )}
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
            <label htmlFor="job-notification-mode">Notification Mode</label>
            <select
              id="job-notification-mode"
              value={form.notification_mode}
              onChange={(e) => setForm((prev) => ({ ...prev, notification_mode: e.target.value }))}
            >
              <option value="channel">Post to Discord</option>
              <option value="silent">Silent background</option>
            </select>
          </div>
          {form.notification_mode === "channel" && (
            <div className="form-group">
              <label htmlFor="job-target-channel">Target Channel</label>
              <input
                id="job-target-channel"
                value={form.target_channel_ref}
                onChange={(e) => setForm((prev) => ({ ...prev, target_channel_ref: e.target.value }))}
                placeholder="#fitness-log or <#123456789012345678>"
              />
            </div>
          )}
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
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.expect_reply}
              onChange={(e) => setForm((prev) => ({ ...prev, expect_reply: e.target.checked }))}
            />
            Expect reply
          </label>
          {form.expect_reply && (
            <div className="form-group" style={{ maxWidth: 220 }}>
              <label htmlFor="job-follow-up-after">Follow up after minutes</label>
              <input
                id="job-follow-up-after"
                type="number"
                min="1"
                max="10080"
                value={form.follow_up_after_minutes}
                onChange={(e) => setForm((prev) => ({ ...prev, follow_up_after_minutes: e.target.value }))}
              />
            </div>
          )}
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
                const status = jobStatusMeta(job);
                const latestRun = runsByJob[job.id]?.[0];
                const latestRunDetail = getJobRunDetail(latestRun);
                const replyState = runReplyStateText(latestRun, job);
                return (
                  <article key={job.id} className="glass-card job-card">
                    <div className="job-card-head">
                      <div className="job-card-summary">
                        <h3>
                          #{job.id} {job.name}
                        </h3>
                        <p className="job-card-meta">
                          Agent: <strong>{job.agent_name || "n/a"}</strong> · Schedule: <strong>{jobScheduleText(job)}</strong> · TZ:{" "}
                          <strong>{job.timezone}</strong>
                        </p>
                        <p className="job-card-meta">Notify: {jobNotifyText(job)}</p>
                        <p className="job-card-meta">
                          Replies: {job.expect_reply ? `expected; follow up after ${job.follow_up_after_minutes || 120} min` : "logged only"}
                        </p>
                        {job.description && <p className="job-card-meta">Description: {job.description}</p>}
                        <p className="job-card-meta">
                          Last run: {job.last_run_at ? formatInTimezone(job.last_run_at, job.timezone) : "never"} · Next run:{" "}
                          {job.next_run_at ? formatInTimezone(job.next_run_at, job.timezone) : "n/a"} · Status:{" "}
                          <span className={`badge ${status.badge}`}>{status.label}</span>
                        </p>
                        {job.completed_at && (
                          <p className="job-card-meta">Completed: {formatInTimezone(job.completed_at, job.timezone)}</p>
                        )}
                        {latestRunDetail && (
                          <p className="job-card-meta">
                            {getJobRunDetailLabel(latestRun?.status)}: {latestRunDetail}
                          </p>
                        )}
                        {replyState && <p className="job-card-meta">Reply state: {replyState}</p>}
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
                              {formatInTimezone(run.created_at, job.timezone, run.created_at)} ·{" "}
                              <span className={`badge ${runStatusBadge(run.status)}`}>{run.status}</span>
                              {getJobRunDetail(run) ? ` · ${getJobRunDetail(run)}` : ""}
                              {runReplyStateText(run, job) ? ` · Reply: ${runReplyStateText(run, job)}` : ""}
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
