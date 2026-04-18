import { expect, test } from "@playwright/test";

const NAV_PAGES = [
  { button: /^Mission Control$/i, heading: /Mission Control/i, slug: "mission-control" },
  { button: /^Today$/i, heading: /Today Focus/i, slug: "today" },
  { button: /^Inbox$/i, heading: /^Inbox$/i, slug: "inbox" },
  { button: /^Prayer$/i, heading: /Prayer Dashboard/i, slug: "prayer" },
  { button: /^Quran$/i, heading: /Quran Log/i, slug: "quran" },
  { button: /^Life Items$/i, heading: /Life Items/i, slug: "life-items" },
  { button: /^Agents$/i, heading: /^Agents$/i, slug: "agents" },
  { button: /^Spawn Agent$/i, heading: /Spawn Agent/i, slug: "spawn-agent" },
  { button: /^Jobs$/i, heading: /Scheduled Jobs/i, slug: "jobs" },
  { button: /^Approvals$/i, heading: /Approval Queue/i, slug: "approvals" },
  { button: /^Providers$/i, heading: /Provider Setup/i, slug: "providers" },
  { button: /^Experiments$/i, heading: /Experiments/i, slug: "experiments" },
  { button: /^Profile$/i, heading: /^Profile$/i, slug: "profile" },
  { button: /^Settings$/i, heading: /Global Settings/i, slug: "settings" },
];

function trackConsoleErrors(page) {
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return errors;
}

function criticalConsoleErrors(errors) {
  return errors.filter((entry) => !/favicon/i.test(entry));
}

async function seedToken(page) {
  await page.addInitScript(() => {
    localStorage.setItem("lifeos_token", "test-token");
  });
}

async function mockApi(page) {
  const jobs = [
    {
      id: 11,
      name: "Morning stretch",
      description: "Mobility check-in",
      enabled: true,
      paused: false,
      agent_name: "planner",
      cron_expression: "30 7 * * mon-fri",
      timezone: "Africa/Casablanca",
      last_run_at: "2026-03-03T07:30:00Z",
      next_run_at: "2026-03-04T07:30:00Z",
      last_status: "success",
      last_error: null,
      approval_required: true,
    },
  ];
  const todayAgenda = {
    timezone: "Africa/Casablanca",
    now: "2026-03-03T12:00:00Z",
    top_focus: [{ id: 2, title: "Deep work block", domain: "work", priority: "high" }],
    due_today: [{ id: 5, title: "Call family", domain: "family", priority: "medium" }],
    overdue: [{ id: 6, title: "Send invoice", domain: "work", priority: "high" }],
    domain_summary: { work: 2, family: 1 },
    intake_summary: { ready: 1, clarifying: 0, parked: 0 },
    ready_intake: [
      {
        id: 21,
        title: "Inbox capture",
        raw_text: "Inbox capture",
        status: "ready",
        domain: "planning",
        kind: "task",
      },
    ],
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
  };

  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace("/api", "");
    const method = req.method();

    if (path === "/events") {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
      return;
    }

    if (path === "/events/auth") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      return;
    }

    if (path === "/health") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "healthy" }) });
      return;
    }
    if (path === "/readiness") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ready", database: true }),
      });
      return;
    }
    if (path === "/approvals/" || path === "/approvals/all") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    if (path === "/profile/") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          timezone: "Africa/Casablanca",
          city: "Casablanca",
          country: "MA",
          prayer_method: 2,
          work_shift_start: "09:00",
          work_shift_end: "18:00",
          quiet_hours_start: "23:00",
          quiet_hours_end: "06:00",
          nudge_mode: "balanced",
        }),
      });
      return;
    }
    if (path === "/settings/") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data_start_date: "2026-03-02",
          default_timezone: "Africa/Casablanca",
          autonomy_enabled: true,
          approval_required_for_mutations: true,
        }),
      });
      return;
    }
    if (path === "/life/today") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(todayAgenda),
      });
      return;
    }
    if (path === "/life/daily-log" && method === "POST") {
      const payload = req.postDataJSON();
      if (payload.kind === "hydration") {
        todayAgenda.scorecard.hydration_count += payload.count || 1;
        todayAgenda.scorecard.rescue_status = "rescue";
        todayAgenda.rescue_plan = {
          status: "rescue",
          headline: "Day needs a rescue plan. Shrink scope and recover anchors first.",
          actions: [
            "Log water twice in the next hour.",
            "Clear or reschedule overdue priority: Send invoice",
          ],
        };
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          kind: payload.kind,
          message: `Logged ${payload.kind}. Meals ${todayAgenda.scorecard.meals_count} | water ${todayAgenda.scorecard.hydration_count} | train unset | priorities 0 | rescue ${todayAgenda.rescue_plan.status}`,
          scorecard: todayAgenda.scorecard,
          rescue_plan: todayAgenda.rescue_plan,
        }),
      });
      return;
    }
    if (path === "/life/items" || path.startsWith("/life/items?")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([{ id: 4, title: "Workout", domain: "health", kind: "habit", status: "open" }]),
      });
      return;
    }
    if (path === "/life/inbox" || path.startsWith("/life/inbox?")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: 21,
            title: "Inbox capture",
            status: "ready",
            domain: "planning",
            kind: "task",
            updated_at: "2026-03-03T08:00:00Z",
            linked_life_item_id: null,
            source_session_id: null,
          },
        ]),
      });
      return;
    }
    if (path === "/prayer/schedule/today") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ next_prayer: "Asr", rows: [] }),
      });
      return;
    }
    if (path === "/prayer/weekly-summary") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ prayer_accuracy_percent: 84 }),
      });
      return;
    }
    if (path === "/prayer/dashboard") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          summary: { on_time: 20, late: 4, missed: 1, unknown: 0 },
          days: [{ date: "2026-03-03", prayers: { Fajr: "on_time", Dhuhr: "late", Asr: "on_time", Maghrib: "missed", Isha: "on_time" } }],
        }),
      });
      return;
    }
    if (path === "/prayer/habits/quran/progress") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ current_page: 10, pages_read_total: 24, completion_pct: 4, recent_readings: [] }),
      });
      return;
    }
    if (path === "/prayer/habits/quran/log" && method === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: 9, start_page: 10, end_page: 12, pages_read: 3, local_date: "2026-03-03" }),
      });
      return;
    }
    if (path === "/agents/") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { id: 1, name: "planner", description: "Plans tasks", enabled: true, provider: "openai", model: "gpt-5" },
        ]),
      });
      return;
    }
    if (path.startsWith("/agents/") && path.endsWith("/sessions")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    if (path === "/providers/") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { name: "openai", available: true, default_model: "gpt-5", base_url: "https://api.openai.com" },
          { name: "anthropic", available: false, default_model: "claude", base_url: "https://api.anthropic.com" },
        ]),
      });
      return;
    }
    if (path === "/providers/capabilities") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tools: { enabled: true }, vision: { enabled: false, reason: "missing key" } }),
      });
      return;
    }
    if (path === "/experiments" || path.startsWith("/experiments?")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          experiments: [
            {
              id: 91,
              created_at: "2026-03-03T08:00:00Z",
              primary_provider: "openai",
              shadow_provider: "anthropic",
              primary_score: 0.51,
              shadow_score: 0.67,
              shadow_latency_ms: 820,
              cost_estimate: 0.00123,
              shadow_wins: true,
              promoted: false,
            },
          ],
        }),
      });
      return;
    }
    if (path === "/experiments/telemetry") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          providers: [
            {
              provider: "openai",
              avg_latency_ms: 740,
              avg_tokens: 812,
              successes: 10,
              failures: 1,
              circuit_open: false,
              last_model: "openai/gpt-5",
            },
          ],
        }),
      });
      return;
    }
    if (path === "/jobs/" && method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(jobs) });
      return;
    }
    if (path === "/jobs/" && method === "POST") {
      const payload = req.postDataJSON();
      const created = {
        id: 99,
        name: payload.name || "New job",
        description: payload.description || "",
        enabled: payload.enabled ?? true,
        paused: false,
        agent_name: payload.agent_name || "planner",
        cron_expression: payload.cron_expression || "30 7 * * mon-fri",
        timezone: payload.timezone || "Africa/Casablanca",
        last_run_at: null,
        next_run_at: "2026-03-04T07:30:00Z",
        last_status: null,
        last_error: null,
        approval_required: payload.approval_required ?? true,
      };
      jobs.unshift(created);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(created) });
      return;
    }
    if (path.startsWith("/jobs/") && path.endsWith("/runs")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([{ id: 1, status: "success", created_at: "2026-03-03T07:30:00Z", error: null }]),
      });
      return;
    }

    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
}

test("smoke: landing, nav pages, status indicators, and console hygiene", async ({ page }, testInfo) => {
  const consoleErrors = trackConsoleErrors(page);
  await mockApi(page);
  await seedToken(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Mission Control/i }).first()).toBeVisible();
  await expect(page.getByText("Workspace connected")).toBeVisible();
  await expect(page.getByText(/Realtime (connected|reconnecting)/i)).toBeVisible();
  await expect(page.getByText("healthy")).toBeVisible();
  await expect(page.getByText("ready")).toBeVisible();
  await expect(page.getByText("connected", { exact: true })).toBeVisible();

  for (const target of NAV_PAGES) {
    await page.getByRole("button", { name: target.button }).first().click();
    await expect(page.getByRole("heading", { name: target.heading }).first()).toBeVisible();

    const header = page.locator(".ui-zen-header").first();
    await expect(header).toBeVisible();
    const box = await header.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect(box?.y ?? -1).toBeGreaterThanOrEqual(0);

    await page.screenshot({ path: testInfo.outputPath(`after-${target.slug}.png`), fullPage: true });
  }

  expect(criticalConsoleErrors(consoleErrors)).toEqual([]);
});

test("primary CTA: jobs form submission", async ({ page }) => {
  await mockApi(page);
  await seedToken(page);
  await page.goto("/");

  await page.getByRole("button", { name: /^Jobs$/i }).first().click();
  await expect(page.getByRole("heading", { name: /Scheduled Jobs/i })).toBeVisible();

  await page.getByLabel("Job Name").fill("Night summary");
  await page.getByLabel("Agent", { exact: true }).selectOption("planner");
  await page.getByRole("button", { name: /create job/i }).click();

  await expect(page.getByText("#99 Night summary")).toBeVisible();
});

test("today quick log updates scorecard", async ({ page }) => {
  await mockApi(page);
  await seedToken(page);
  await page.goto("/");

  await page.getByRole("button", { name: /^Today$/i }).first().click();
  await expect(page.getByRole("heading", { name: /Today Focus/i }).first()).toBeVisible();
  await expect(page.getByText("Hydration is behind.")).toBeVisible();

  await page.getByRole("button", { name: "Water +1" }).click();

  await expect(page.getByText(/Logged hydration\./i)).toBeVisible();
  await expect(page.getByText("Day needs a rescue plan. Shrink scope and recover anchors first.")).toBeVisible();
});
