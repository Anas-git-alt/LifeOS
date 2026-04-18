import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import TodayView from "./TodayView";

const apiMocks = vi.hoisted(() => ({
  getTodayAgenda: vi.fn(async () => ({
    timezone: "Africa/Casablanca",
    now: "2026-03-03T12:00:00Z",
    top_focus: [{ id: 1, title: "Deep work block", domain: "work", priority: "high" }],
    due_today: [{ id: 2, title: "Call family", domain: "family", priority: "medium" }],
    overdue: [{ id: 3, title: "Send invoice", domain: "work", priority: "high" }],
    domain_summary: { work: 2, family: 1 },
    intake_summary: { ready: 1, clarifying: 0, parked: 0 },
    ready_intake: [{ id: 9, title: "Inbox capture", raw_text: "Inbox capture", status: "ready", domain: "planning", kind: "task" }],
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
  logDailySignal: vi.fn(async () => ({
    kind: "hydration",
    message: "Logged hydration. Meals 1 | water 2 | train unset | priorities 0 | rescue rescue",
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
      rescue_status: "rescue",
      notes: {},
      created_at: "2026-03-03T08:00:00Z",
      updated_at: "2026-03-03T08:10:00Z",
    },
    rescue_plan: {
      status: "rescue",
      headline: "Day needs a rescue plan. Shrink scope and recover anchors first.",
      actions: ["Log water twice in the next hour.", "Clear or reschedule overdue priority: Send invoice"],
    },
  })),
}));

vi.mock("../api", () => apiMocks);

describe("TodayView", () => {
  test("renders scorecard and applies quick logs", async () => {
    render(<TodayView />);

    await screen.findByText("Hydration is behind.");
    expect(screen.getAllByText("Asr").length).toBeGreaterThan(0);
    expect(screen.getByText("7.5h")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Water +1" }));

    await waitFor(() =>
      expect(apiMocks.logDailySignal).toHaveBeenCalledWith({ kind: "hydration", count: 1 }),
    );
    await screen.findByText(/Logged hydration\./i);
    expect(screen.getByText("Day needs a rescue plan. Shrink scope and recover anchors first.")).toBeInTheDocument();
    expect(screen.getByText("Clear or reschedule overdue priority: Send invoice")).toBeInTheDocument();
  });
});
