import { describe, expect, test } from "vitest";

import { getJobRunDetail, getJobRunDetailLabel } from "./jobRuns";

describe("jobRuns", () => {
  test("extracts reason from scheduler dict string", () => {
    expect(
      getJobRunDetail({
        status: "skipped",
        message: "{'status': 'skipped', 'reason': 'memory_unavailable'}",
        error: null,
      }),
    ).toBe("memory unavailable");
  });

  test("prefers explicit error", () => {
    expect(
      getJobRunDetail({
        status: "failed",
        message: "{'status': 'skipped', 'reason': 'memory_unavailable'}",
        error: "provider timeout",
      }),
    ).toBe("provider timeout");
  });

  test("maps detail labels by status", () => {
    expect(getJobRunDetailLabel("skipped")).toBe("Skip reason");
    expect(getJobRunDetailLabel("failed")).toBe("Failure detail");
    expect(getJobRunDetailLabel("completed")).toBe("Run detail");
  });
});
