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
  // NOTE: localStorage is accessible to any JS on the page (XSS risk).
  // For a self-hosted personal tool on localhost this is an acceptable
  // trade-off, but do NOT store sensitive data or use this pattern in
  // a multi-user or internet-facing deployment.
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
export const archiveAgentSession = (agentName, sessionId, source = "webui") =>
  request(`/agents/${agentName}/sessions/${sessionId}/archive`, {
    method: "POST",
    body: JSON.stringify({ source }),
  });
export const archiveAllAgentSessions = (agentName, source = "webui") =>
  request(`/agents/${agentName}/sessions/archive-all`, {
    method: "POST",
    body: JSON.stringify({ source }),
  });
export const listArchivedAgentSessions = (agentName, limit = 100) =>
  request(`/agents/${agentName}/session-archives?limit=${limit}`);
export const restoreAgentSessionArchive = (agentName, archiveId, source = "webui") =>
  request(`/agents/${agentName}/session-archives/${archiveId}/restore`, {
    method: "POST",
    body: JSON.stringify({ source }),
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

export const getWorkspaceArchives = (agentName = "", limit = 100) => {
  const query = new URLSearchParams();
  if (agentName) query.set("agent_name", agentName);
  if (limit) query.set("limit", String(limit));
  return request(`/workspace/archives${query.toString() ? `?${query.toString()}` : ""}`);
};
export const restoreWorkspaceArchive = (archiveEntryId, sourceAgent = "webui") =>
  request(`/workspace/archives/${archiveEntryId}/restore`, {
    method: "POST",
    body: JSON.stringify({ source_agent: sourceAgent }),
  });
export const syncWorkspaceResources = (paths = []) =>
  request("/workspace/sync", {
    method: "POST",
    body: JSON.stringify({ paths }),
    timeoutMs: 30000,
  });

export const getProviders = () => request("/providers/");
export const getCapabilities = () => request("/providers/capabilities");
export const getTtsModels = () => request("/tts/models");
export const previewAgentVoice = (agentName, text = "", language = null) =>
  request("/tts/preview", {
    method: "POST",
    body: JSON.stringify({ agent_name: agentName, text, language }),
    timeoutMs: 30000,
  });
export const synthesizeAgentVoice = (agentName, text, language = null, queuePolicy = "replace", runtimeOverrides = null) =>
  request("/tts/synthesize", {
    method: "POST",
    body: JSON.stringify({
      agent_name: agentName,
      text,
      language,
      queue_policy: queuePolicy,
      runtime_overrides: runtimeOverrides,
    }),
    timeoutMs: 45000,
  });
export const getTtsHealth = () => request("/tts/health");
export const startVoiceSession = (guildId, channelId, agentName, queuePolicy = "replace") =>
  request("/voice/sessions/start", {
    method: "POST",
    body: JSON.stringify({
      guild_id: String(guildId),
      channel_id: String(channelId),
      agent_name: agentName,
      queue_policy: queuePolicy,
    }),
  });
export const interruptVoiceSession = (sessionId, reason = "") =>
  request(`/voice/sessions/${sessionId}/interrupt`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
export const stopVoiceSession = (sessionId, reason = "") =>
  request(`/voice/sessions/${sessionId}/stop`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

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
export const getIntakeInbox = (params = {}) => {
  const query = new URLSearchParams(params).toString();
  return request(`/life/inbox${query ? `?${query}` : ""}`);
};
export const getIntakeEntry = (entryId) => request(`/life/inbox/${entryId}`);
export const updateIntakeEntry = (entryId, data) =>
  request(`/life/inbox/${entryId}`, { method: "PUT", body: JSON.stringify(data) });
export const captureIntake = (message, sessionId = null, newSession = false, source = "webui") =>
  request("/life/inbox/capture", {
    method: "POST",
    body: JSON.stringify({
      message,
      session_id: sessionId,
      new_session: newSession,
      source,
    }),
    timeoutMs: 30000,
  });
export const promoteIntakeEntry = (entryId, data = {}) =>
  request(`/life/inbox/${entryId}/promote`, { method: "POST", body: JSON.stringify(data) });

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
export const resetQuranProgress = () => request("/prayer/habits/quran/reset", { method: "POST", body: JSON.stringify({}) });

export async function getAgentSessionsSummary(limitAgents = 5) {
  const agents = await getAgents();
  const topAgents = agents.slice(0, limitAgents);
  const sessions = await Promise.all(
    topAgents.map(async (agent) => {
      try {
        const rows = await listAgentSessions(agent.name);
        return rows.map((row) => ({ ...row, agent_name: agent.name }));
      } catch (err) {
        // Log the error so developers can diagnose issues; return empty array
        // so the summary still renders for agents that succeeded.
        console.error(`[getAgentSessionsSummary] failed for agent '${agent.name}':`, err);
        return [];
      }
    }),
  );

  return sessions
    .flat()
    .sort((a, b) => new Date(b.last_message_at || b.updated_at || 0) - new Date(a.last_message_at || a.updated_at || 0));
}

export const getExperiments = (limit = 50) => request(`/experiments?limit=${limit}`);
export const getProviderTelemetry = () => request('/experiments/telemetry');
