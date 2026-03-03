/**
 * LifeOS API client.
 * Uses X-LifeOS-Token from localStorage (lifeos_token) or VITE_LIFEOS_TOKEN.
 */

const API_BASE = "/api";
const DEFAULT_TIMEOUT_MS = 12000;

export class ApiError extends Error {
  constructor(message, { kind = "server", status = 0, detail = "", cause = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
    this.cause = cause;
  }
}

export function getToken() {
  return localStorage.getItem("lifeos_token") || import.meta.env.VITE_LIFEOS_TOKEN || "";
}

export function setToken(token) {
  localStorage.setItem("lifeos_token", token || "");
}

function withTimeout(timeoutMs) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  return { controller, timeoutId };
}

function normalizeApiError(error, resp = null) {
  if (error instanceof ApiError) return error;

  if (error?.name === "AbortError") {
    return new ApiError("Request timed out", { kind: "network", status: 0, cause: error });
  }

  if (resp?.status === 401) {
    return new ApiError("Missing or invalid X-LifeOS-Token", {
      kind: "auth",
      status: 401,
      detail: "Missing or invalid X-LifeOS-Token",
      cause: error,
    });
  }

  if (resp) {
    return new ApiError(error?.message || `API error: ${resp.status}`, {
      kind: "server",
      status: resp.status,
      detail: error?.message || resp.statusText,
      cause: error,
    });
  }

  return new ApiError(error?.message || "Network request failed", {
    kind: "network",
    status: 0,
    cause: error,
  });
}

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const token = getToken();
  const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;

  const headers = { ...(options.headers || {}) };
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!isFormData && !headers["Content-Type"] && options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers["X-LifeOS-Token"] = token;

  const { controller, timeoutId } = withTimeout(timeoutMs);
  let resp;
  try {
    resp = await fetch(url, {
      ...options,
      headers,
      credentials: options.credentials || "same-origin",
      signal: controller.signal,
    });
  } catch (error) {
    clearTimeout(timeoutId);
    throw normalizeApiError(error);
  }
  clearTimeout(timeoutId);

  let payload = null;
  const contentType = resp.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  if (isJson) {
    payload = await resp.json().catch(() => null);
  } else if (options.expectText) {
    payload = await resp.text().catch(() => "");
  }

  if (!resp.ok) {
    const detail = payload?.detail || resp.statusText || `API error: ${resp.status}`;
    throw normalizeApiError(new Error(detail), resp);
  }

  return payload;
}

export async function ensureEventsSession() {
  await request("/events/auth", { method: "POST" });
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

export const getJobs = (agentName = "") =>
  request(`/jobs/${agentName ? `?agent_name=${encodeURIComponent(agentName)}` : ""}`);
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
export const updateLifeItem = (id, data) => request(`/life/items/${id}`, { method: "PUT", body: JSON.stringify(data) });
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

export const getPrayerScheduleToday = () => request("/prayer/schedule/today");
export const getPrayerWeeklySummary = () => request("/prayer/weekly-summary");

// Quran page-based tracking
export const logQuranReading = (endPage, startPage = null, note = null) =>
  request("/prayer/habits/quran/log", {
    method: "POST",
    body: JSON.stringify({ end_page: endPage, start_page: startPage, note }),
  });
export const getQuranProgress = () => request("/prayer/habits/quran/progress");
export const getQuranBookmark = () => request("/prayer/habits/quran/bookmark");

export async function getAgentSessionsSummary(limitAgents = 5) {
  const agents = await getAgents();
  const topAgents = agents.slice(0, limitAgents);
  const sessions = await Promise.all(
    topAgents.map(async (agent) => {
      try {
        const rows = await listAgentSessions(agent.name);
        return rows.map((row) => ({ ...row, agent_name: agent.name }));
      } catch {
        return [];
      }
    }),
  );

  return sessions
    .flat()
    .sort((a, b) => new Date(b.last_message_at || b.updated_at || 0) - new Date(a.last_message_at || a.updated_at || 0));
}
