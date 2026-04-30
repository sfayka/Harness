import assert from "node:assert/strict";
import test from "node:test";

import { fetchTaskDetail } from "../../lib/harness-api";

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("maps read-model execution transport summary fields", async () => {
  const responses = new Map<string, unknown>([
    [
      "/api/harness/tasks/task-1/read-model",
      {
        task: {
          task_id: "task-1",
          title: "Execution transport projection",
          description: "Verify latest transport status maps into the dashboard model.",
          current_status: "blocked",
          objective_summary: null,
          origin: {
            source_system: "harness",
            source_type: "test",
            source_id: "task-1",
          },
          relationships: {},
          evidence_summary: {},
          review_summary: {},
          evaluation_summary: {},
          timestamps: {
            created_at: "2026-04-30T19:00:00Z",
            updated_at: "2026-04-30T19:01:00Z",
            completed_at: null,
          },
          execution_summary: {
            attempt_count: 1,
            latest_status: "blocked",
            latest_dispatch_origin: "automatic",
            latest_execution_transport_status: "disabled",
            latest_live_dispatch_enabled: false,
            latest_completion_authority: "harness_verification",
            latest_runner_completion_is_truth: false,
          },
        },
      },
    ],
    ["/api/harness/tasks/task-1/timeline", { timeline: [] }],
  ]);

  globalThis.fetch = async (url) => {
    const payload = responses.get(String(url));
    assert.notEqual(payload, undefined, `unexpected URL ${url}`);
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const task = await fetchTaskDetail("task-1");

  assert.equal(task.execution_summary?.attempt_count, 1);
  assert.equal(task.execution_summary?.latest_status, "blocked");
  assert.equal(task.execution_summary?.latest_dispatch_origin, "automatic");
  assert.equal(task.execution_summary?.latest_execution_transport_status, "disabled");
  assert.equal(task.execution_summary?.latest_live_dispatch_enabled, false);
  assert.equal(task.execution_summary?.latest_completion_authority, "harness_verification");
  assert.equal(task.execution_summary?.latest_runner_completion_is_truth, false);
});
