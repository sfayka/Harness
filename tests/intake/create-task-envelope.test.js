import test from "node:test";
import assert from "node:assert/strict";

import { createTaskEnvelope } from "../../src/harness/intake/index.js";
import {
  assertValidTaskEnvelope,
  validateTaskEnvelope
} from "../../src/contracts/task-envelope/validate-task-envelope.js";

test("createTaskEnvelope maps intake input into a valid TaskEnvelope", () => {
  const taskEnvelope = createTaskEnvelope(
    {
      id: "task-123",
      title: "Draft architecture baseline",
      description: "Normalize this inbound request into the canonical task contract.",
      origin: {
        source_system: "openclaw",
        source_type: "ingress_request",
        source_id: "req-123",
        ingress_id: "session-001",
        ingress_name: "OpenClaw",
        requested_by: "user-42"
      },
      objective: {
        summary: "Create the first canonical TaskEnvelope for the request.",
        deliverable_type: "document",
        success_signal: "A valid TaskEnvelope exists and can be routed downstream."
      },
      constraints: [
        {
          type: "scope",
          description: "Do not implement planner behavior.",
          required: true
        }
      ],
      acceptance_criteria: [
        {
          id: "ac-1",
          description: "Envelope validates against the JSON Schema.",
          required: true
        }
      ]
    },
    {
      now: "2026-03-24T12:00:00.000Z"
    }
  );

  assert.equal(taskEnvelope.id, "task-123");
  assert.equal(taskEnvelope.status, "intake_ready");
  assert.deepEqual(taskEnvelope.timestamps, {
    created_at: "2026-03-24T12:00:00.000Z",
    updated_at: "2026-03-24T12:00:00.000Z",
    completed_at: null
  });
  assert.equal(taskEnvelope.parent_task_id, null);
  assert.deepEqual(taskEnvelope.child_task_ids, []);
  assert.deepEqual(taskEnvelope.dependencies, []);
  assert.equal(taskEnvelope.assigned_executor, null);
  assert.deepEqual(taskEnvelope.required_capabilities, []);
  assert.equal(taskEnvelope.priority, "normal");
  assert.deepEqual(taskEnvelope.artifacts, {
    pr_links: [],
    commit_shas: [],
    logs: [],
    outputs: []
  });
  assert.equal(taskEnvelope.objective.deliverable_type, "document");

  assert.doesNotThrow(() => assertValidTaskEnvelope(taskEnvelope));
});

test("createTaskEnvelope populates intake defaults for planner-owned and dispatcher-owned fields", () => {
  const taskEnvelope = createTaskEnvelope(
    {
      title: "Investigate flaky test failure",
      description: "Determine what is needed to unblock execution.",
      origin: {
        source_system: "openclaw",
        source_type: "ingress_request",
        source_id: "req-456"
      },
      acceptance_criteria: [
        {
          description: "Task is represented in the canonical schema."
        }
      ]
    },
    {
      now: "2026-03-24T12:15:00.000Z"
    }
  );

  assert.equal(taskEnvelope.status, "intake_ready");
  assert.equal(taskEnvelope.objective.summary, "Determine what is needed to unblock execution.");
  assert.equal(taskEnvelope.objective.deliverable_type, "unspecified");
  assert.equal(
    taskEnvelope.objective.success_signal,
    "Task satisfies declared acceptance criteria."
  );
  assert.deepEqual(taskEnvelope.constraints, []);
  assert.deepEqual(taskEnvelope.status_history, []);
  assert.deepEqual(taskEnvelope.observability.retries, {
    attempt_count: 0,
    max_attempts: 0,
    last_retry_at: null
  });
  assert.deepEqual(taskEnvelope.observability.execution_metadata.intake_deferred_fields, [
    "parent_task_id",
    "child_task_ids",
    "dependencies",
    "assigned_executor",
    "required_capabilities",
    "artifacts",
    "observability.errors",
    "observability.execution_metadata"
  ]);
});

test("schema validation reports invalid TaskEnvelope objects", () => {
  const result = validateTaskEnvelope({
    id: "bad-task"
  });

  assert.equal(result.valid, false);
  assert.ok(result.errors.length > 0);
});

test("createTaskEnvelope rejects missing required intake fields", () => {
  assert.throws(
    () =>
      createTaskEnvelope({
        description: "Missing a title.",
        origin: {
          source_system: "openclaw",
          source_type: "ingress_request",
          source_id: "req-789"
        },
        acceptance_criteria: [
          {
            description: "Should not be created."
          }
        ]
      }),
    /title/
  );
});

test("createTaskEnvelope rejects empty acceptance criteria", () => {
  assert.throws(
    () =>
      createTaskEnvelope({
        title: "Investigate failure mode",
        description: "Missing completion conditions.",
        origin: {
          source_system: "openclaw",
          source_type: "ingress_request",
          source_id: "req-999"
        },
        acceptance_criteria: []
      }),
    /acceptanceCriteria/
  );
});
