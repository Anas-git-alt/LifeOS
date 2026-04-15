import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import JobsManager from "./JobsManager";

vi.mock("../api", () => ({
  createJob: vi.fn(),
  deleteJob: vi.fn(),
  getAgents: vi.fn(async () => [{ name: "sandbox" }]),
  getJobRuns: vi.fn(async () => [
    {
      id: 101,
      status: "skipped",
      message: "{'status': 'skipped', 'reason': 'memory_unavailable'}",
      error: null,
      created_at: "2026-03-02T07:30:00Z",
    },
  ]),
  getJobs: vi.fn(async () => [
    {
      id: 11,
      name: "Morning stretch",
      agent_name: "sandbox",
      schedule_type: "cron",
      cron_expression: "30 7 * * mon-fri",
      run_at: null,
      timezone: "Africa/Casablanca",
      notification_mode: "channel",
      target_channel: "fitness-log",
      target_channel_id: "123456789012345678",
      prompt_template: "Stretch now",
      enabled: true,
      paused: false,
      approval_required: true,
      source: "manual",
      created_by: "webui",
      config_json: null,
      last_run_at: null,
      next_run_at: null,
      last_status: null,
      last_error: null,
      created_at: "2026-03-02T00:00:00Z",
      updated_at: "2026-03-02T00:00:00Z",
    },
  ]),
  pauseJob: vi.fn(async () => ({})),
  resumeJob: vi.fn(async () => ({})),
  updateJob: vi.fn(),
}));

describe("JobsManager", () => {
  test("renders existing jobs and triggers pause", async () => {
    const { pauseJob } = await import("../api");
    render(<JobsManager />);

    await screen.findByText(/Morning stretch/i);
    await screen.findByText(/Skip reason: memory unavailable/i);
    fireEvent.click(screen.getByRole("button", { name: /^pause$/i }));

    await waitFor(() => expect(pauseJob).toHaveBeenCalledWith(11));
  });

  test("submits a one-time silent job", async () => {
    const { createJob } = await import("../api");
    render(<JobsManager />);

    await screen.findByRole("heading", { name: /scheduled jobs/i });
    fireEvent.change(screen.getByLabelText("Job Name"), { target: { value: "Quick review" } });
    fireEvent.change(screen.getByLabelText("Agent"), { target: { value: "sandbox" } });
    fireEvent.change(screen.getByLabelText("Schedule Type"), { target: { value: "once" } });
    fireEvent.change(screen.getByLabelText("Run At"), { target: { value: "2026-03-25T09:00" } });
    fireEvent.change(screen.getByLabelText("Notification Mode"), { target: { value: "silent" } });
    fireEvent.click(screen.getByRole("button", { name: /create job/i }));

    await waitFor(() =>
      expect(createJob).toHaveBeenCalledWith(
        expect.objectContaining({
          schedule_type: "once",
          run_at: "2026-03-25T09:00:00",
          notification_mode: "silent",
          target_channel: null,
          target_channel_id: null,
        }),
      ),
    );
  });
});
