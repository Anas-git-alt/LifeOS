import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import JobsManager from "./JobsManager";

vi.mock("../api", () => ({
  createJob: vi.fn(),
  deleteJob: vi.fn(),
  getAgents: vi.fn(async () => [{ name: "sandbox" }]),
  getJobRuns: vi.fn(async () => []),
  getJobs: vi.fn(async () => [
    {
      id: 11,
      name: "Morning stretch",
      agent_name: "sandbox",
      cron_expression: "30 7 * * mon-fri",
      timezone: "Africa/Casablanca",
      target_channel: "fitness-log",
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
    fireEvent.click(screen.getByRole("button", { name: /^pause$/i }));

    await waitFor(() => expect(pauseJob).toHaveBeenCalledWith(11));
  });
});
