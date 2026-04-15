const RUN_REASON_LABELS = {
  agent_disabled_or_missing: "agent disabled or missing",
  job_disabled_or_paused: "job disabled or paused",
  job_missed_startup_window: "job missed startup window",
  job_not_found: "job not found",
  llm_unavailable: "LLM unavailable",
  memory_unavailable: "memory unavailable",
  pending_approval: "pending approval",
};

function normalizeText(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function humanizeCode(value) {
  const normalized = normalizeText(value);
  if (!normalized) return "";
  return RUN_REASON_LABELS[normalized] || normalized.replace(/[_-]+/g, " ");
}

function extractObjectField(message, field) {
  const normalized = normalizeText(message);
  if (!normalized.startsWith("{")) return "";
  const match = normalized.match(new RegExp(`['"]${field}['"]\\s*:\\s*['"]([^'"]+)['"]`));
  return normalizeText(match?.[1]);
}

export function getJobRunDetail(run) {
  if (!run) return "";
  if (run.error) return normalizeText(run.error);

  const message = normalizeText(run.message);
  if (!message) return "";

  const reason = extractObjectField(message, "reason");
  if (reason) return humanizeCode(reason);

  const status = extractObjectField(message, "status");
  if (status === "pending_approval") return humanizeCode(status);

  if (/^[a-z0-9_-]+$/i.test(message)) return humanizeCode(message);
  if (message.startsWith("{") && message.endsWith("}")) return "";
  return message;
}

export function getJobRunDetailLabel(status) {
  const normalized = normalizeText(status).toLowerCase();
  if (normalized === "skipped") return "Skip reason";
  if (normalized === "failed") return "Failure detail";
  if (normalized === "pending_approval") return "Pending detail";
  return "Run detail";
}
