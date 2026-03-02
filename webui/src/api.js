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
export const chatWithAgent = (agentName, message, approvalPolicy = "auto") =>
  request("/agents/chat", {
    method: "POST",
    body: JSON.stringify({ agent_name: agentName, message, approval_policy: approvalPolicy }),
  });
export const runScheduledAgent = (agentName) => request(`/agents/${agentName}/run-scheduled`, { method: "POST" });

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
