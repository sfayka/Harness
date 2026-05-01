import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchExecutionSubstrateHandoffs,
  fetchExecutionSubstrateTransportStatus,
} from "../../lib/harness-api";

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("maps execution substrate handoff previews from Harness", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/proofline/execution-substrate/handoffs");
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
            completion_validation_summary: {
              status: "blocked",
              summary: "Completion was claimed, but Proofline has not validated it against intent and evidence.",
              intent_status: "not_validated",
              evidence_status: "insufficient",
              reconciliation_status: "pending",
              completion_claimed: true,
              completion_accepted: false,
              manual_review_status: "none",
              automatic_completion_safe: false,
              verification_outcome: "insufficient_evidence",
              reasons: ["Completion evidence is missing a verified pull request."],
              required_criteria_count: 2,
              concrete_required_criteria_count: 2,
              required_artifact_types: ["pull_request"],
              validated_artifact_ids: [],
              validated_artifact_count: 0,
            },
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
  assert.equal(preview.handoffs[0].completion_validation_summary?.status, "blocked");
  assert.equal(preview.handoffs[0].completion_validation_summary?.completion_accepted, false);
  assert.equal(preview.handoffs[0].completion_validation_summary?.evidence_status, "insufficient");
  assert.equal(preview.handoffs[0].handoff.metadata.safe_to_execute_live, false);
  assert.equal(
    preview.handoffs[0].handoff.callback.events_endpoint,
    "/tasks/task-1/execution-substrate-events",
  );
});

test("maps execution substrate transport status from Harness", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/proofline/execution-substrate/transport-status");
    return new Response(
      JSON.stringify({
        generated_at: "2026-04-30T16:50:00Z",
        substrate_kind: "symphony-compatible",
        preferred_runner: "symphony",
        transport_status: "disabled",
        dispatch_enabled: false,
        live_dispatch_enabled: false,
        advisory_only: true,
        completion_authority: "harness_verification",
        runner_completion_is_truth: false,
        safe_to_execute_live: false,
        events_contract: "execution_substrate_event.v1",
        handoff_preview_endpoint: "/execution-substrate/handoffs",
        intents_endpoint: "/execution-substrate/intents",
        message: "Symphony live dispatch is disabled.",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  const status = await fetchExecutionSubstrateTransportStatus();

  assert.equal(status.transport_status, "disabled");
  assert.equal(status.preferred_runner, "symphony");
  assert.equal(status.dispatch_enabled, false);
  assert.equal(status.live_dispatch_enabled, false);
  assert.equal(status.completion_authority, "harness_verification");
  assert.equal(status.runner_completion_is_truth, false);
  assert.equal(status.safe_to_execute_live, false);
});
