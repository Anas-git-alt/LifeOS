import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import WikiView from "./WikiView";

vi.mock("../api", () => ({
  applyMemoryProposal: vi.fn(async () => ({ status: "applied" })),
  captureMeetingSummary: vi.fn(async () => ({
    event: { id: 7, domain: "work", status: "curated" },
    proposals: [{ id: 3 }],
    intake_entry_ids: [9],
  })),
  curateMemoryEvent: vi.fn(async () => ({ event: { id: 4 }, proposals: [], intake_entry_ids: [] })),
  getMemoryEvents: vi.fn(async () => [
    {
      id: 7,
      title: "Planning Sync",
      event_type: "meeting_summary",
      domain: "work",
      status: "curated",
      summary: "Decision: build the wiki.",
      raw_text: "Decision: build the wiki.",
    },
  ]),
  getVaultConflicts: vi.fn(async () => [
    {
      id: 3,
      title: "Planning Sync",
      domain: "work",
      conflict_reason: "review_required",
      target_path: "/vault/shared/domains/work/planning-sync.md",
    },
  ]),
}));

describe("WikiView", () => {
  test("submits meeting summary and renders proposals", async () => {
    const { captureMeetingSummary } = await import("../api");
    render(<WikiView />);

    await screen.findByText(/review_required/i);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Client Sync" } });
    fireEvent.change(screen.getByLabelText("Domain"), { target: { value: "work" } });
    fireEvent.change(screen.getByLabelText("Meeting Summary"), {
      target: { value: "Decision: connect agents through Obsidian. Action: add wiki page." },
    });
    fireEvent.click(screen.getByRole("button", { name: /capture meeting/i }));

    await waitFor(() =>
      expect(captureMeetingSummary).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Client Sync",
          domain: "work",
          summary: "Decision: connect agents through Obsidian. Action: add wiki page.",
        }),
      ),
    );
    await screen.findByText(/Captured event #7/i);
  });

  test("applies pending proposal", async () => {
    const { applyMemoryProposal } = await import("../api");
    render(<WikiView />);

    await screen.findByText(/review_required/i);
    fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    await waitFor(() => expect(applyMemoryProposal).toHaveBeenCalledWith(3, "webui"));
  });
});
