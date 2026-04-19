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
    sleep_protocol: {
      bedtime_target: "23:30",
      wake_target: "07:30",
      caffeine_cutoff: "15:00",
      wind_down_checklist: ["Dim lights and put phone away", "Set tomorrow's first step"],
      sleep_hours_logged: 7.5,
      bedtime_logged: "23:40",
      wake_time_logged: "07:10",
    },
    streaks: [
      { key: "sleep", label: "Sleep 7h+", current_streak: 3, hits_last_7: 5, today_status: "hit" },
      { key: "hydration", label: "Hydration 2+", current_streak: 2, hits_last_7: 4, today_status: "pending" },
    ],
    trend_summary: {
      window_days: 7,
      average_completion_pct: 71,
      best_day: { date: "2026-03-02", hits: 6, total: 7, completion_pct: 86 },
      recent_days: [
        { date: "2026-03-01", hits: 4, total: 7, completion_pct: 57 },
        { date: "2026-03-02", hits: 6, total: 7, completion_pct: 86 },
      ],
    },
  })),
  getDailyFocusCoach: vi.fn(async () => ({
    primary_item_id: 1,
    why_now: "Overdue high-priority commitment.",
    first_step: "Open the deep work doc and finish the first paragraph.",
    defer_ids: [2],
    nudge_copy: "Move Deep work block one visible step before opening anything new.",
    fallback_used: false,
  })),
  getWeeklyCommitmentReview: vi.fn(async () => ({
    wins: ["Closed 2 commitments this week."],
    stale_commitments: ["Send invoice"],
    repeat_blockers: ["Snoozed commitments 2 times."],
    promises_at_risk: ["Call family"],
    simplify_next_week: ["Keep only 3 active commitments."],
    fallback_used: false,
  })),
  logDailySignal: vi.fn(async (payload) => ({
    kind: payload.kind,
    message: payload.kind === "sleep"
      ? "Logged sleep. Meals 1 | water 1 | train unset | priorities 0 | rescue watch"
      : "Logged hydration. Meals 1 | water 2 | train unset | priorities 0 | rescue rescue",
    scorecard: {
      id: 1,
      local_date: "2026-03-03",
      timezone: "Africa/Casablanca",
      sleep_hours: payload.kind === "sleep" ? 8 : 7.5,
      sleep_summary: payload.kind === "sleep"
        ? { hours: 8, bedtime: "23:20", wake_time: "07:20", note: "solid night" }
        : { hours: 7.5 },
      meals_count: 1,
      training_status: null,
      hydration_count: payload.kind === "sleep" ? 1 : 2,
      shutdown_done: false,
      protein_hit: false,
      family_action_done: false,
      top_priority_completed_count: 0,
      rescue_status: payload.kind === "sleep" ? "watch" : "rescue",
      notes: {},
      created_at: "2026-03-03T08:00:00Z",
      updated_at: "2026-03-03T08:10:00Z",
    },
    rescue_plan: payload.kind === "sleep"
      ? {
          status: "watch",
          headline: "Hydration is behind.",
          actions: ["Log water twice in the next hour."],
        }
      : {
          status: "rescue",
          headline: "Day needs a rescue plan. Shrink scope and recover anchors first.",
          actions: ["Log water twice in the next hour.", "Clear or reschedule overdue priority: Send invoice"],
        },
    sleep_protocol: {
      bedtime_target: "23:30",
      wake_target: "07:30",
      caffeine_cutoff: "15:00",
      wind_down_checklist: ["Dim lights and put phone away", "Set tomorrow's first step"],
      sleep_hours_logged: payload.kind === "sleep" ? 8 : 7.5,
      bedtime_logged: payload.kind === "sleep" ? "23:20" : "23:40",
      wake_time_logged: payload.kind === "sleep" ? "07:20" : "07:10",
    },
    streaks: [
      { key: "sleep", label: "Sleep 7h+", current_streak: 3, hits_last_7: 5, today_status: "hit" },
      { key: "hydration", label: "Hydration 2+", current_streak: 3, hits_last_7: 5, today_status: "hit" },
    ],
    trend_summary: {
      window_days: 7,
      average_completion_pct: 74,
      best_day: { date: "2026-03-02", hits: 6, total: 7, completion_pct: 86 },
      recent_days: [
        { date: "2026-03-01", hits: 4, total: 7, completion_pct: 57 },
        { date: "2026-03-02", hits: 6, total: 7, completion_pct: 86 },
      ],
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
    expect(screen.getByText("Commitment Radar")).toBeInTheDocument();
    expect(screen.getByText("AI Focus Coach")).toBeInTheDocument();
    expect(screen.getByText("Deep work block")).toBeInTheDocument();
    expect(screen.getByText("Caffeine cutoff 15:00")).toBeInTheDocument();
    expect(screen.getByText("Sleep 7h+")).toBeInTheDocument();
    expect(screen.getByText("71%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Water +1" }));

    await waitFor(() =>
      expect(apiMocks.logDailySignal).toHaveBeenCalledWith({ kind: "hydration", count: 1 }),
    );
    await screen.findByText(/Logged hydration\./i);
    expect(screen.getByText("Day needs a rescue plan. Shrink scope and recover anchors first.")).toBeInTheDocument();
    expect(screen.getByText("Clear or reschedule overdue priority: Send invoice")).toBeInTheDocument();
    expect(screen.getAllByText("3d streak · 5/7 hits").length).toBeGreaterThan(0);
    expect(screen.getByText("74%")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Sleep hours"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Bedtime"), { target: { value: "23:20" } });
    fireEvent.change(screen.getByLabelText("Wake time"), { target: { value: "07:20" } });
    fireEvent.change(screen.getByLabelText("Sleep note"), { target: { value: "solid night" } });
    fireEvent.click(screen.getByRole("button", { name: "Log Sleep" }));

    await waitFor(() =>
      expect(apiMocks.logDailySignal).toHaveBeenCalledWith({
        kind: "sleep",
        hours: 8,
        bedtime: "23:20",
        wake_time: "07:20",
        note: "solid night",
      }),
    );
    expect(screen.getByText("Latest sleep log: 23:20 → 07:20")).toBeInTheDocument();
  });
});
