import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import App from "./App";

const apiMocks = vi.hoisted(() => ({
  ensureEventsSession: vi.fn(async () => ({})),
  getHealth: vi.fn(async () => ({ status: "healthy" })),
  getReadiness: vi.fn(async () => ({ status: "ready", database: true })),
  getPendingActions: vi.fn(async () => [{ id: 10, agent_name: "planner", summary: "Review daily plan", status: "pending", created_at: "2026-03-03T08:00:00Z" }]),
  getAllActions: vi.fn(async () => [{ id: 10, agent_name: "planner", summary: "Review daily plan", status: "approved", created_at: "2026-03-03T08:00:00Z" }]),
  decideAction: vi.fn(async () => ({})),
  getJobs: vi.fn(async () => [{ id: 11, name: "Morning stretch", agent_name: "planner", cron_expression: "30 7 * * mon-fri", timezone: "Africa/Casablanca", enabled: true, paused: false, next_run_at: "2026-03-04T07:30:00Z", last_run_at: null, last_error: null }]),
  getJobRuns: vi.fn(async () => [{ id: 1, status: "success", created_at: "2026-03-03T07:30:00Z", error: null }]),
  createJob: vi.fn(async () => ({ id: 12 })),
  updateJob: vi.fn(async () => ({})),
  pauseJob: vi.fn(async () => ({})),
  resumeJob: vi.fn(async () => ({})),
  deleteJob: vi.fn(async () => ({})),
  getTodayAgenda: vi.fn(async () => ({ timezone: "Africa/Casablanca", now_local: "2026-03-03 12:00", top_focus: [{ id: 1, title: "Deep work", domain: "work", priority: "high" }], domain_summary: { work: 1 } })),
  getPrayerScheduleToday: vi.fn(async () => ({ next_prayer: "Asr", rows: [] })),
  getPrayerWeeklySummary: vi.fn(async () => ({ prayer_accuracy_percent: 84 })),
  getAgentSessionsSummary: vi.fn(async () => [{ id: 7, agent_name: "planner", title: "Daily plan", updated_at: "2026-03-03T08:00:00Z" }]),
  getPrayerDashboard: vi.fn(async () => ({ summary: { on_time: 20, late: 4, missed: 1, unknown: 0 }, days: [{ date: "2026-03-03", prayers: { Fajr: "on_time", Dhuhr: "late", Asr: "on_time", Maghrib: "missed", Isha: "on_time" } }] })),
  editPrayerCheckin: vi.fn(async () => ({})),
  getQuranProgress: vi.fn(async () => ({ current_page: 10, total_pages_read: 24, completion_percent: 4, recent_readings: [] })),
  getQuranBookmark: vi.fn(async () => ({ current_page: 10 })),
  logQuranReading: vi.fn(async () => ({})),
  getLifeItems: vi.fn(async () => [{ id: 4, title: "Workout", domain: "health", kind: "habit", status: "open" }]),
  createLifeItem: vi.fn(async () => ({ id: 8 })),
  updateLifeItem: vi.fn(async () => ({})),
  checkinLifeItem: vi.fn(async () => ({})),
  getAgents: vi.fn(async () => [{ id: 1, name: "planner", description: "Plans the day", provider: "openai", model: "gpt-5", enabled: true }]),
  deleteAgent: vi.fn(async () => ({})),
  createAgent: vi.fn(async () => ({})),
  getProviders: vi.fn(async () => [{ name: "openai", available: true, default_model: "gpt-5", base_url: "https://api.openai.com" }, { name: "anthropic", available: false, default_model: "claude", base_url: "https://api.anthropic.com" }]),
  getCapabilities: vi.fn(async () => ({ vision: { enabled: true }, tools: { enabled: false, reason: "disabled in config" } })),
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

    await screen.findAllByRole("heading", { name: "Mission Control" });
    fireEvent.click(screen.getByRole("button", { name: /^Today$/i }));
    await screen.findByRole("heading", { name: "Today Focus" });

    const pages = ["Prayer", "Quran", "Life Items", "Agents", "Spawn Agent", "Jobs", "Approvals", "Providers", "Profile", "Settings"];
    for (const label of pages) {
      fireEvent.click(screen.getAllByRole("button", { name: new RegExp(label, "i") })[0]);
    }

    await screen.findByRole("heading", { name: "Global Settings" });
    expect(screen.getByText("Workspace connected")).toBeInTheDocument();
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  test("uses green/red status badges on providers", async () => {
    renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: /^Providers$/i })[0]);

    const configured = await screen.findByText("Configured");
    const noApiKey = await screen.findByText("No API Key");

    expect(configured.className).toContain("badge-approved");
    expect(noApiKey.className).toContain("badge-rejected");
  });

  test("submits the jobs form", async () => {
    renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: /^Jobs$/i })[0]);
    await screen.findByRole("heading", { name: "Cron Jobs" });

    fireEvent.change(screen.getByLabelText("Job Name"), { target: { value: "Night summary" } });
    fireEvent.change(screen.getByLabelText("Agent"), { target: { value: "planner" } });
    fireEvent.click(screen.getByRole("button", { name: /create job/i }));

    await waitFor(() => expect(apiMocks.createJob).toHaveBeenCalled());
  });
});
