/**
 * LifeOS API client.
 * Uses X-LifeOS-Token from localStorage (lifeos_token) or VITE_LIFEOS_TOKEN.
 */

const API_BASE = "/api";

function getToken() {
  return localStorage.getItem("lifeos_token") || import.meta.env.VITE_LIFEOS_TOKEN || "";
}

export function setToken(token) {
  localStorage.setItem("lifeos_token", token || "");
}

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const token = getToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers["X-LifeOS-Token"] = token;

  const resp = await fetch(url, { ...options, headers });
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(error.detail || `API error: ${resp.status}`);
  }
  return resp.json();
}

export const getAgents = () => request("/agents/");
export const getAgent = (name) => request(`/agents/${name}`);
export const createAgent = (data) => request("/agents/", { method: "POST", body: JSON.stringify(data) });
export const updateAgent = (name, data) => request(`/agents/${name}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteAgent = (name) => request(`/agents/${name}`, { method: "DELETE" });
export const chatWithAgent = (agentName, message, approvalPolicy = "auto", sessionId = null) =>
  request("/agents/chat", {
    method: "POST",
    body: JSON.stringify({
      agent_name: agentName,
      message,
      approval_policy: approvalPolicy,
      session_id: sessionId,
    }),
  });
export const runScheduledAgent = (agentName) => request(`/agents/${agentName}/run-scheduled`, { method: "POST" });
export const listAgentSessions = (agentName) => request(`/agents/${agentName}/sessions`);
export const createAgentSession = (agentName, title = null) =>
  request(`/agents/${agentName}/sessions`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
export const renameAgentSession = (agentName, sessionId, title) =>
  request(`/agents/${agentName}/sessions/${sessionId}`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
export const clearAgentSession = (agentName, sessionId) =>
  request(`/agents/${agentName}/sessions/${sessionId}/clear`, {
    method: "POST",
    body: JSON.stringify({}),
  });
export const getAgentSessionMessages = (agentName, sessionId, limit = 200) =>
  request(`/agents/${agentName}/sessions/${sessionId}/messages?limit=${limit}`);

export const getPendingActions = () => request("/approvals/");
export const getAllActions = () => request("/approvals/all");
export const decideAction = (actionId, approved, reason = "", reviewedBy = "webui") =>
  request("/approvals/decide", {
    method: "POST",
    body: JSON.stringify({
      action_id: actionId,
      approved,
      reason,
      reviewed_by: reviewedBy,
      source: "webui",
    }),
  });
export const getApprovalStats = () => request("/approvals/stats");

export const getProviders = () => request("/providers/");
export const getCapabilities = () => request("/providers/capabilities");

export const getHealth = () => request("/health");
export const getReadiness = () => request("/readiness");

export const getProfile = () => request("/profile/");
export const updateProfile = (data) => request("/profile/", { method: "PUT", body: JSON.stringify(data) });
export const getSettings = () => request("/settings/");
export const updateSettings = (data) => request("/settings/", { method: "PUT", body: JSON.stringify(data) });

export const getJobs = (agentName = "") => request(`/jobs/${agentName ? `?agent_name=${encodeURIComponent(agentName)}` : ""}`);
export const getJob = (jobId) => request(`/jobs/${jobId}`);
export const createJob = (data) => request("/jobs/", { method: "POST", body: JSON.stringify(data) });
export const updateJob = (jobId, data) => request(`/jobs/${jobId}`, { method: "PUT", body: JSON.stringify(data) });
export const pauseJob = (jobId) => request(`/jobs/${jobId}/pause`, { method: "POST", body: JSON.stringify({}) });
export const resumeJob = (jobId) => request(`/jobs/${jobId}/resume`, { method: "POST", body: JSON.stringify({}) });
export const deleteJob = (jobId) => request(`/jobs/${jobId}`, { method: "DELETE" });
export const getJobRuns = (jobId, limit = 20) => request(`/jobs/${jobId}/runs?limit=${limit}`);
export const proposeJob = (summary, details) =>
  request("/jobs/propose", {
    method: "POST",
    body: JSON.stringify({ summary, details, source: "webui", requested_by: "webui" }),
  });
export const proposeAgent = (summary, details) =>
  request("/agents/propose", {
    method: "POST",
    body: JSON.stringify({ summary, details, source: "webui", requested_by: "webui" }),
  });

export const getLifeItems = (params = {}) => {
  const query = new URLSearchParams(params).toString();
  return request(`/life/items${query ? `?${query}` : ""}`);
};
export const createLifeItem = (data) => request("/life/items", { method: "POST", body: JSON.stringify(data) });
export const updateLifeItem = (id, data) =>
  request(`/life/items/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const checkinLifeItem = (id, result, note = "") =>
  request(`/life/items/${id}/checkin`, { method: "POST", body: JSON.stringify({ result, note }) });
export const getTodayAgenda = () => request("/life/today");
export const getGoalProgress = (itemId) => request(`/life/items/${itemId}/progress`);

// Prayer dashboard
export const getPrayerDashboard = (endDate = null) => {
  const query = endDate ? `?end_date=${endDate}` : "";
  return request(`/prayer/dashboard${query}`);
};
export const editPrayerCheckin = (prayerDate, prayerName, status, note = null) =>
  request("/prayer/checkin/edit", {
    method: "PUT",
    body: JSON.stringify({ prayer_date: prayerDate, prayer_name: prayerName, status, note }),
  });

// Quran page-based tracking
export const logQuranReading = (endPage, startPage = null, note = null) =>
  request("/prayer/habits/quran/log", {
    method: "POST",
    body: JSON.stringify({ end_page: endPage, start_page: startPage, note }),
  });
export const getQuranProgress = () => request("/prayer/habits/quran/progress");
export const getQuranBookmark = () => request("/prayer/habits/quran/bookmark");
