import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AgentConfig from "./AgentConfig";

let resolveChat;

const apiMocks = vi.hoisted(() => ({
  archiveAgentSession: vi.fn(async () => ({})),
  archiveAllAgentSessions: vi.fn(async () => ({})),
  chatWithAgent: vi.fn(() => new Promise((resolve) => {
    resolveChat = resolve;
  })),
  clearAgentSession: vi.fn(async () => ({})),
  createAgentSession: vi.fn(async () => ({
    id: 7,
    agent_name: "sandbox",
    title: "Main session",
    prompt_seed_count: 0,
    created_at: "2026-03-03T08:00:00Z",
    updated_at: "2026-03-03T08:00:00Z",
    last_message_at: "2026-03-03T08:00:00Z",
  })),
  getAgent: vi.fn(async () => ({
    name: "sandbox",
    description: "Sandbox",
    system_prompt: "You are sandbox.",
    provider: "openrouter",
    model: "openrouter/free",
    fallback_provider: "",
    fallback_model: "",
    discord_channel: "",
    cadence: "",
    enabled: true,
    speech_enabled: false,
    tts_engine: "chatterbox_turbo",
    tts_model_id: "chatterbox-turbo",
    voice_id: "",
    default_language: "en",
    voice_instructions: "",
    preview_text: "Preview",
    reference_audio_path: "",
    voice_visible_in_runtime_picker: true,
    workspace_enabled: true,
    workspace_paths: ["/workspace"],
    workspace_delete_requires_approval: true,
    voice_params_json: {},
  })),
  getAgentSessionMessages: vi
    .fn()
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([
      { id: "m1", role: "user", content: "Reply with exactly: OK", timestamp: "2026-03-03T08:00:00Z" },
      { id: "m2", role: "assistant", content: "OK", timestamp: "2026-03-03T08:00:10Z" },
    ]),
  getProviders: vi.fn(async () => [{ name: "openrouter", available: true }]),
  getTtsModels: vi.fn(async () => []),
  getWorkspaceArchives: vi.fn(async () => []),
  listArchivedAgentSessions: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [{
    id: 7,
    agent_name: "sandbox",
    title: "Main session",
    prompt_seed_count: 0,
    created_at: "2026-03-03T08:00:00Z",
    updated_at: "2026-03-03T08:00:00Z",
    last_message_at: "2026-03-03T08:00:00Z",
  }]),
  previewAgentVoice: vi.fn(async () => ({ audio_b64_wav: "" })),
  renameAgentSession: vi.fn(async () => ({})),
  restoreAgentSessionArchive: vi.fn(async () => ({})),
  restoreWorkspaceArchive: vi.fn(async () => ({})),
  syncWorkspaceResources: vi.fn(async () => ({ items: [] })),
  updateAgent: vi.fn(async () => ({})),
}));

vi.mock("../api", () => apiMocks);

describe("AgentConfig chat", () => {
  test("shows thinking status and preserves backend warnings", async () => {
    render(<AgentConfig agentName="sandbox" onBack={() => {}} />);

    await screen.findByRole("heading", { name: "sandbox" });
    const sessionLabels = await screen.findAllByText("Main session");
    expect(sessionLabels.length).toBeGreaterThan(0);

    fireEvent.change(screen.getByPlaceholderText("Message sandbox..."), {
      target: { value: "Reply with exactly: OK" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    const thinkingMarkers = await screen.findAllByText("Thinking...");
    expect(thinkingMarkers.length).toBeGreaterThan(0);
    expect(screen.getByText(/View request status/i)).toBeInTheDocument();

    resolveChat({
      agent_name: "sandbox",
      response: "OK",
      pending_action_id: null,
      risk_level: "low",
      session_id: 7,
      session_title: "Main session",
      warnings: [
        "OpenViking memory was unavailable for this turn, so the reply was generated without prior session context.",
      ],
    });

    await screen.findByText("OK");
    await waitFor(() =>
      expect(
        screen.getByText(/OpenViking memory was unavailable for this turn/i),
      ).toBeInTheDocument(),
    );
  });
});
