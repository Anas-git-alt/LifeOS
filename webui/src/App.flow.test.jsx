import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import App from "./App";

const NAV_EXPECTATIONS = [
  { label: /^Mission Control$/i, heading: "Mission Control" },
  { label: /^Today$/i, heading: "Today Focus" },
  { label: /^Inbox$/i, heading: "Inbox" },
  { label: /^Wiki$/i, heading: "Wiki Context" },
  { label: /^Prayer$/i, heading: "Prayer Dashboard" },
  { label: /^Quran$/i, heading: "Quran Log" },
  { label: /^Life Items$/i, heading: "Life Items" },
  { label: /^Agents$/i, heading: "Agents" },
  { label: /^Spawn Agent$/i, heading: "Spawn Agent" },
  { label: /^Jobs$/i, heading: "Scheduled Jobs" },
  { label: /^Approvals$/i, heading: "Approval Queue" },
  { label: /^Providers$/i, heading: "Provider Setup" },
  { label: /^Experiments$/i, heading: /Experiments/i },
  { label: /^Profile$/i, heading: "Profile" },
  { label: /^Settings$/i, heading: "Global Settings" },
];

const apiMocks = vi.hoisted(() => ({
  ensureEventsSession: vi.fn(async () => ({})),
  getHealth: vi.fn(async () => ({ status: "healthy" })),
  getReadiness: vi.fn(async () => ({ status: "ready", database: true })),
  getPendingActions: vi.fn(async () => [{ id: 10, agent_name: "planner", summary: "Review daily plan", status: "pending", created_at: "2026-03-03T08:00:00Z" }]),
  getAllActions: vi.fn(async () => [{ id: 10, agent_name: "planner", summary: "Review daily plan", status: "approved", created_at: "2026-03-03T08:00:00Z" }]),
  decideAction: vi.fn(async () => ({})),
  getJobs: vi.fn(async () => [{ id: 11, name: "Morning stretch", agent_name: "planner", schedule_type: "cron", cron_expression: "30 7 * * mon-fri", run_at: null, timezone: "Africa/Casablanca", notification_mode: "channel", target_channel: "planning", target_channel_id: "123456789012345678", enabled: true, paused: false, expect_reply: false, follow_up_after_minutes: null, next_run_at: "2026-03-04T07:30:00Z", last_run_at: null, completed_at: null, last_error: null }]),
  getJobRuns: vi.fn(async () => [{ id: 1, status: "success", created_at: "2026-03-03T07:30:00Z", error: null }]),
  createJob: vi.fn(async () => ({ id: 12 })),
  updateJob: vi.fn(async () => ({})),
  pauseJob: vi.fn(async () => ({})),
  resumeJob: vi.fn(async () => ({})),
  deleteJob: vi.fn(async () => ({})),
  logDailySignal: vi.fn(async () => ({
    kind: "hydration",
    message: "Logged hydration. Meals 1 | water 2 | train unset | priorities 0 | rescue watch",
    scorecard: {
      id: 1,
      local_date: "2026-03-03",
      timezone: "Africa/Casablanca",
      sleep_hours: 7.5,
      sleep_summary: { hours: 7.5 },
      meals_count: 1,
      training_status: null,
      hydration_count: 2,
      shutdown_done: false,
      protein_hit: false,
      family_action_done: false,
      top_priority_completed_count: 0,
      rescue_status: "watch",
      notes: {},
      created_at: "2026-03-03T08:00:00Z",
      updated_at: "2026-03-03T08:10:00Z",
    },
    rescue_plan: {
      status: "watch",
      headline: "Hydration is behind.",
      actions: ["Log water twice in the next hour."],
    },
  })),
  getDailyFocusCoach: vi.fn(async () => ({
    primary_item_id: 1,
    why_now: "High-priority open commitment.",
    first_step: "Start the first visible step now.",
    defer_ids: [2],
    nudge_copy: "Move Deep work one step before opening new loops.",
    fallback_used: false,
  })),
  getWeeklyCommitmentReview: vi.fn(async () => ({
    wins: ["Closed 1 commitment."],
    stale_commitments: ["none"],
    repeat_blockers: ["none"],
    promises_at_risk: ["none"],
    simplify_next_week: ["Keep only 3 active commitments."],
    fallback_used: false,
  })),
  getTodayAgenda: vi.fn(async () => ({
    timezone: "Africa/Casablanca",
    now: "2026-03-03T12:00:00Z",
    top_focus: [{ id: 1, title: "Deep work", domain: "work", priority: "high" }],
    due_today: [{ id: 2, title: "Call family", domain: "family", priority: "medium" }],
    overdue: [],
    domain_summary: { work: 1 },
    intake_summary: { ready: 1, clarifying: 0, parked: 0 },
    ready_intake: [{ id: 21, title: "Inbox capture", raw_text: "Inbox capture", status: "ready", domain: "planning", kind: "task" }],
    scorecard: {
      id: 1,
      local_date: "2026-03-03",
      timezone: "Africa/Casablanca",
      sleep_hours: 7.5,
      sleep_summary: { hours: 7.5 },
      meals_count: 1,
      training_status: null,
      hydration_count: 1,
      shutdown_done: false,
      protein_hit: false,
      family_action_done: false,
      top_priority_completed_count: 0,
      rescue_status: "watch",
      notes: {},
      created_at: "2026-03-03T08:00:00Z",
      updated_at: "2026-03-03T08:00:00Z",
    },
    next_prayer: {
      name: "Asr",
      starts_at: "2026-03-03T15:30:00Z",
      ends_at: "2026-03-03T18:45:00Z",
    },
    rescue_plan: {
      status: "watch",
      headline: "Hydration is behind.",
      actions: ["Log water twice in the next hour."],
    },
  })),
  getPrayerScheduleToday: vi.fn(async () => ({ next_prayer: "Asr", rows: [] })),
  getPrayerWeeklySummary: vi.fn(async () => ({ prayer_accuracy_percent: 84 })),
  getAgentSessionsSummary: vi.fn(async () => [{ id: 7, agent_name: "planner", title: "Daily plan", updated_at: "2026-03-03T08:00:00Z" }]),
  getIntakeInbox: vi.fn(async () => [{ id: 21, title: "Inbox capture", status: "ready", domain: "planning", kind: "task", updated_at: "2026-03-03T08:00:00Z", linked_life_item_id: null, source_session_id: null }]),
  getAgentSessionMessages: vi.fn(async () => []),
  captureIntake: vi.fn(async () => ({ session_id: 77, entry: { id: 21 } })),
  updateIntakeEntry: vi.fn(async () => ({})),
  promoteIntakeEntry: vi.fn(async () => ({ life_item: { id: 31, title: "Inbox capture" } })),
  captureMeetingSummary: vi.fn(async () => ({ event: { id: 44, domain: "work", status: "curated" }, proposals: [], intake_entry_ids: [] })),
  getMemoryEvents: vi.fn(async () => []),
  curateMemoryEvent: vi.fn(async () => ({ event: { id: 44 }, proposals: [], intake_entry_ids: [] })),
  getVaultConflicts: vi.fn(async () => []),
  applyMemoryProposal: vi.fn(async () => ({ status: "applied" })),
  getPrayerDashboard: vi.fn(async () => ({ summary: { on_time: 20, late: 4, missed: 1, unknown: 0 }, days: [{ date: "2026-03-03", prayers: { Fajr: "on_time", Dhuhr: "late", Asr: "on_time", Maghrib: "missed", Isha: "on_time" } }] })),
  editPrayerCheckin: vi.fn(async () => ({})),
  getQuranProgress: vi.fn(async () => ({ current_page: 10, total_pages_read: 24, completion_percent: 4, recent_readings: [] })),
  getQuranBookmark: vi.fn(async () => ({ current_page: 10 })),
  logQuranReading: vi.fn(async () => ({})),
  getLifeItems: vi.fn(async () => [{ id: 4, title: "Workout", domain: "health", kind: "habit", status: "open" }]),
  createLifeItem: vi.fn(async () => ({ id: 8 })),
  updateLifeItem: vi.fn(async () => ({})),
  checkinLifeItem: vi.fn(async () => ({})),
  getAgents: vi.fn(async () => [{ id: 1, name: "planner", description: "Plans the day", provider: "openrouter", model: "openrouter/free", enabled: true }]),
  deleteAgent: vi.fn(async () => ({})),
  createAgent: vi.fn(async () => ({})),
  getProviders: vi.fn(async () => [
    {
      name: "openrouter",
      available: true,
      default_model: "openrouter/free",
      base_url: "https://openrouter.ai/api/v1",
      free_mode_allowed: true,
      free_mode_reason: null,
    },
    {
      name: "openai",
      available: false,
      default_model: "gpt-4o-mini",
      base_url: "https://api.openai.com/v1",
      free_mode_allowed: false,
      free_mode_reason: "free_only_mode blocks provider `openai`",
    },
  ]),
  getCapabilities: vi.fn(async () => ({ vision: { enabled: true }, tools: { enabled: false, reason: "disabled in config" } })),
  getExperiments: vi.fn(async () => ({
    experiments: [
      {
        id: 91,
        created_at: "2026-03-03T08:00:00Z",
        primary_provider: "openai",
        shadow_provider: "anthropic",
        primary_score: 0.51,
        shadow_score: 0.67,
        shadow_latency_ms: 820,
        cost_estimate: 0.00123,
        shadow_wins: true,
        promoted: false,
      },
    ],
    shadow_router_enabled: false,
    free_only_mode: true,
  })),
  getProviderTelemetry: vi.fn(async () => ({
    shadow_router_enabled: false,
    free_only_mode: true,
    providers: [
      {
        provider: "openai",
        avg_latency_ms: 740,
        avg_tokens: 812,
        successes: 10,
        failures: 1,
        circuit_open: false,
        last_model: "openai/gpt-5",
      },
    ],
  })),
  getProfile: vi.fn(async () => ({ timezone: "Africa/Casablanca", city: "Casablanca", country: "MA", prayer_method: 2, work_shift_start: "09:00", work_shift_end: "18:00", quiet_hours_start: "23:00", quiet_hours_end: "06:00", nudge_mode: "balanced" })),
  updateProfile: vi.fn(async () => ({})),
  getSettings: vi.fn(async () => ({ data_start_date: "2026-03-02", default_timezone: "Africa/Casablanca", autonomy_enabled: true, approval_required_for_mutations: true })),
  updateSettings: vi.fn(async () => ({})),
  setToken: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

class MockEventSource {
  constructor() {
    setTimeout(() => {
      if (this.onopen) this.onopen();
    }, 0);
  }

  close() {}
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App flow smoke", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem("lifeos_token", "test-token");
    window.EventSource = MockEventSource;
  });

  test("navigates top-level pages and keeps console clean", async () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderApp();

    await screen.findAllByRole("heading", { name: "Today Focus" });
    for (const target of NAV_EXPECTATIONS) {
      fireEvent.click(screen.getAllByRole("button", { name: target.label })[0]);
      const headings = await screen.findAllByRole("heading", { name: target.heading });
      expect(headings.length).toBeGreaterThan(0);
    }

    expect(screen.getByText("Workspace connected")).toBeInTheDocument();
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  test("uses green/red status badges on providers", async () => {
    renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: /^Providers$/i })[0]);

    const configured = await screen.findByText("Free-mode ready");
    const noApiKey = await screen.findByText("No API Key");

    expect(configured.className).toContain("badge-approved");
    expect(noApiKey.className).toContain("badge-rejected");
  });

  test("submits the jobs form", async () => {
    renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: /^Jobs$/i })[0]);
    await screen.findByRole("heading", { name: "Scheduled Jobs" });

    fireEvent.change(screen.getByLabelText("Job Name"), { target: { value: "Night summary" } });
    fireEvent.change(screen.getByLabelText("Agent"), { target: { value: "planner" } });
    fireEvent.click(screen.getByRole("button", { name: /create job/i }));

    await waitFor(() => expect(apiMocks.createJob).toHaveBeenCalled());
  });
});
