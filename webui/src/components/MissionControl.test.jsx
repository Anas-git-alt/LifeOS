import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import MissionControl from "./MissionControl";

vi.mock("../hooks/useEventStream", () => ({
  useEventStream: () => ({ status: "connected" }),
}));

const apiMocks = vi.hoisted(() => ({
  getHealth: vi.fn(async () => ({ status: "healthy" })),
  getReadiness: vi.fn(async () => ({ status: "ready", database: true })),
  getPendingActions: vi.fn(async () => []),
  getPrayerScheduleToday: vi.fn(async () => ({ next_prayer: "Asr", rows: [] })),
  getPrayerWeeklySummary: vi.fn(async () => ({ prayer_accuracy_percent: 84 })),
  getTodayAgenda: vi.fn(async () => ({ top_focus: [] })),
  getAgentSessionsSummary: vi.fn(async () => []),
  getJobs: vi.fn(async () =>
    Array.from({ length: 9 }, (_, index) => ({
      id: index + 1,
      name: `Job ${index + 1}`,
      agent_name: "sandbox",
      schedule_type: "once",
      cron_expression: null,
      run_at: `2026-04-24T0${(index % 9) + 1}:00:00Z`,
      timezone: "Africa/Casablanca",
      notification_mode: "channel",
      target_channel: "test",
      target_channel_id: null,
      enabled: false,
      paused: false,
      expect_reply: true,
      follow_up_after_minutes: 5,
      next_run_at: null,
      last_run_at: `2026-04-24T1${index}:00:00Z`,
      completed_at: `2026-04-24T1${index}:00:00Z`,
      last_status: "delivered",
      last_error: null,
      created_at: `2026-04-24T0${(index % 9) + 1}:00:00Z`,
      updated_at: `2026-04-24T1${index}:00:00Z`,
    })),
  ),
  getJobRuns: vi.fn(async (jobId) => [
    {
      id: 100 + jobId,
      status: "delivered",
      message: "{'status': 'delivered'}",
      error: null,
      reply_count: jobId === 9 ? 1 : 0,
      awaiting_reply_until: "2026-04-24T12:05:00Z",
      no_reply_follow_up_sent_at: null,
      created_at: "2026-04-24T12:00:00Z",
    },
  ]),
}));

vi.mock("../api", () => apiMocks);

function renderMissionControl() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MissionControl hasToken onNavigate={() => {}} onChangeToken={() => {}} />
    </QueryClientProvider>,
  );
}

describe("MissionControl", () => {
  test("loads run logs for expanded jobs and shows completed reply status", async () => {
    renderMissionControl();

    await screen.findByRole("heading", { name: /Mission Control/i });
    const jobsCard = screen.getByRole("heading", { name: /^Jobs$/i }).closest("section");
    fireEvent.click(within(jobsCard).getByRole("button", { name: /show more/i }));

    await screen.findByText(/#9 Job 9/i);
    await screen.findByText(/Reply: 1 reply received/i);
    await waitFor(() => expect(apiMocks.getJobRuns).toHaveBeenCalledWith(9, 3));
  });
});
