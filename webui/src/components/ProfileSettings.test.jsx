import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import ProfileSettings from "./ProfileSettings";

vi.mock("../api", () => ({
  getProfile: vi.fn(async () => ({
    id: 1,
    timezone: "Africa/Casablanca",
    city: "Casablanca",
    country: "Morocco",
    prayer_method: 2,
    work_shift_start: "14:00",
    work_shift_end: "00:00",
    quiet_hours_start: "23:00",
    quiet_hours_end: "06:00",
    nudge_mode: "moderate",
    sleep_bedtime_target: "23:30",
    sleep_wake_target: "07:30",
    sleep_caffeine_cutoff: "15:00",
    sleep_wind_down_checklist: ["Dim lights and put phone away", "Set tomorrow's first step"],
  })),
  updateProfile: vi.fn(async (payload) => ({
    ...payload,
    id: 1,
    created_at: "2026-03-02T00:00:00Z",
    updated_at: "2026-03-02T00:00:00Z",
  })),
}));

describe("ProfileSettings", () => {
  test("loads and saves sleep protocol fields", async () => {
    const { updateProfile } = await import("../api");
    render(<ProfileSettings />);

    await screen.findByText("Sleep Protocol");
    fireEvent.change(screen.getByLabelText("Bedtime Target"), { target: { value: "23:00" } });
    fireEvent.change(screen.getByLabelText("Wake Target"), { target: { value: "07:00" } });
    fireEvent.change(screen.getByLabelText("Caffeine Cutoff"), { target: { value: "14:00" } });
    fireEvent.change(screen.getByLabelText("Wind-Down Checklist"), {
      target: { value: "Dim lights\nPrep clothes\nPhone away" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateProfile).toHaveBeenCalled());
    expect(updateProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        sleep_bedtime_target: "23:00",
        sleep_wake_target: "07:00",
        sleep_caffeine_cutoff: "14:00",
        sleep_wind_down_checklist: ["Dim lights", "Prep clothes", "Phone away"],
      }),
    );
  });
});
