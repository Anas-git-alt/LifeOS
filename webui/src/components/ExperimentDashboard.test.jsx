import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import ExperimentDashboard from "./ExperimentDashboard";

const apiMocks = vi.hoisted(() => ({
  getExperiments: vi.fn(),
  getProviderTelemetry: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

function makeExperiment(overrides = {}) {
  return {
    id: 1,
    created_at: "2026-04-15T08:00:00Z",
    primary_provider: "openrouter",
    primary_model: "openrouter/auto",
    shadow_provider: "nvidia",
    shadow_model: "meta/llama-3.1-8b-instruct",
    primary_score: 0.7,
    shadow_score: 0.9,
    shadow_latency_ms: 820,
    cost_estimate: 0.00021,
    shadow_wins: true,
    promoted: false,
    promotion_approved: null,
    ...overrides,
  };
}

describe("ExperimentDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getProviderTelemetry.mockResolvedValue({ providers: [] });
  });

  test("does not claim a promotion request exists for a shadow win alone", async () => {
    apiMocks.getExperiments.mockResolvedValue({
      experiments: [makeExperiment()],
      pending_promotions: [],
    });

    render(<ExperimentDashboard />);

    await screen.findByText("Shadow wins");
    expect(screen.queryByText(/Promotion request pending/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Approval Queue to decide whether to promote/i)).not.toBeInTheDocument();
  });

  test("shows promotion banner only when backend reports a pending request", async () => {
    apiMocks.getExperiments.mockResolvedValue({
      experiments: [makeExperiment()],
      pending_promotions: ["nvidia"],
    });

    render(<ExperimentDashboard />);

    expect(await screen.findByText("Promotion request pending")).toBeInTheDocument();
    expect(
      screen.getByText(/Shadow provider "nvidia" hit the promotion threshold/i)
    ).toBeInTheDocument();
  });

  test("empty-state copy matches successful-call sampling behavior", async () => {
    apiMocks.getExperiments.mockResolvedValue({
      experiments: [],
      pending_promotions: [],
    });

    render(<ExperimentDashboard />);

    expect(await screen.findByText("No shadow tests run yet.")).toBeInTheDocument();
    expect(
      screen.getByText(/~5% of successful LLM calls when multiple healthy providers are configured/i)
    ).toBeInTheDocument();
  });
});
