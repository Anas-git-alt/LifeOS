import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import GlobalSettings from "./GlobalSettings";

vi.mock("../api", () => ({
  getSettings: vi.fn(async () => ({
    data_start_date: "2026-03-02",
    default_timezone: "Africa/Casablanca",
    autonomy_enabled: true,
    approval_required_for_mutations: true,
  })),
  updateSettings: vi.fn(async (payload) => ({
    ...payload,
    id: 1,
    created_at: "2026-03-02T00:00:00Z",
    updated_at: "2026-03-02T00:00:00Z",
  })),
}));

describe("GlobalSettings", () => {
  test("loads and saves data start date", async () => {
    const { updateSettings } = await import("../api");
    render(<GlobalSettings />);

    await screen.findByText("Global Settings");
    const input = screen.getByLabelText("Data Start Date");
    fireEvent.change(input, { target: { value: "2026-03-10" } });
    fireEvent.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
    expect(updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        data_start_date: "2026-03-10",
      })
    );
  });
});
