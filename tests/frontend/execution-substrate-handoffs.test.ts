import assert from "node:assert/strict";
import test from "node:test";

import { fetchExecutionSubstrateHandoffs } from "../../lib/harness-api";

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("maps execution substrate handoff previews from Harness", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/harness/execution-substrate/handoffs");
    return new Response(
      JSON.stringify({
        generated_at: "2026-04-30T15:00:00Z",
        handoff_count: 1,
        source: "execution_substrate_intents",
        advisory_only: true,
        dispatch_enabled: false,
        completion_authority: "harness_verification",
        handoffs: [
          {
            task_id: "task-1",
            attention_type: "retryable_failure",
            current_status: "blocked",
            last_activity_at: null,
            handoff: {
              adapter: "symphony-execution-substrate",
              mode: "render_only",
              intent: {
                intent_type: "retry_execution",
                substrate_kind: "symphony-compatible",
                task_id: "task-1",
                source: "harness_supervision_queue",
                reason: "Task is retryable.",
                suggested_action: "retry_or_redispatch",
                advisory_only: true,
                events_endpoint: "/tasks/task-1/execution-substrate-events",
                completion_authority: "harness_verification",
                prohibited_actions: ["mark_harness_complete"],
              },
              harness_boundary: {
                completion_authority: "harness_verification",
                advisory_only: true,
                runner_completion_is_truth: false,
                artifact_verification_required: true,
              },
              runner_policy: {
                substrate_kind: "symphony-compatible",
                allowed_intent_type: "retry_execution",
                prohibited_actions: ["mark_harness_complete"],
              },
              callback: {
                events_endpoint: "/tasks/task-1/execution-substrate-events",
                events_url: "http://harness.test/tasks/task-1/execution-substrate-events",
                event_contract: "execution_substrate_event.v1",
              },
              metadata: {
                task_id: "task-1",
                source: "harness_supervision_queue",
                safe_to_execute_live: false,
              },
            },
          },
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  const preview = await fetchExecutionSubstrateHandoffs();

  assert.equal(preview.handoff_count, 1);
  assert.equal(preview.dispatch_enabled, false);
  assert.equal(preview.completion_authority, "harness_verification");
  assert.equal(preview.handoffs[0].handoff.mode, "render_only");
  assert.equal(preview.handoffs[0].handoff.metadata.safe_to_execute_live, false);
  assert.equal(
    preview.handoffs[0].handoff.callback.events_endpoint,
    "/tasks/task-1/execution-substrate-events",
  );
});
