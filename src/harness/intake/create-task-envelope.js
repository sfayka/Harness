import crypto from "node:crypto";

import { assertValidTaskEnvelope } from "../../contracts/task-envelope/validate-task-envelope.js";

function isoTimestamp(date = new Date()) {
  return date.toISOString();
}

function normalizeString(value, fieldName) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`Expected non-empty string for ${fieldName}`);
  }

  return value.trim();
}

function normalizeOptionalString(value) {
  if (value == null) {
    return null;
  }

  return normalizeString(value, "optional string");
}

function normalizeConstraints(constraints = []) {
  if (!Array.isArray(constraints)) {
    throw new Error("Expected constraints to be an array");
  }

  return constraints.map((constraint, index) => ({
    type: normalizeString(constraint.type, `constraints[${index}].type`),
    description: normalizeString(
      constraint.description,
      `constraints[${index}].description`
    ),
    required: constraint.required !== false
  }));
}

function normalizeAcceptanceCriteria(acceptanceCriteria = []) {
  if (!Array.isArray(acceptanceCriteria)) {
    throw new Error("Expected acceptanceCriteria to be an array");
  }

  if (acceptanceCriteria.length === 0) {
    throw new Error("Expected acceptanceCriteria to contain at least one item");
  }

  return acceptanceCriteria.map((criterion, index) => ({
    id: normalizeString(
      criterion.id ?? `criterion-${index + 1}`,
      `acceptanceCriteria[${index}].id`
    ),
    description: normalizeString(
      criterion.description,
      `acceptanceCriteria[${index}].description`
    ),
    required: criterion.required !== false
  }));
}

function normalizeOrigin(origin) {
  if (!origin || typeof origin !== "object") {
    throw new Error("Expected origin to be an object");
  }

  return {
    source_system: normalizeString(origin.source_system, "origin.source_system"),
    source_type: normalizeString(origin.source_type, "origin.source_type"),
    source_id: normalizeString(origin.source_id, "origin.source_id"),
    ingress_id: normalizeOptionalString(origin.ingress_id),
    ingress_name: normalizeOptionalString(origin.ingress_name),
    requested_by: normalizeOptionalString(origin.requested_by)
  };
}

function normalizeObjective(input) {
  const summary = normalizeString(
    input.objective?.summary ?? input.description,
    "objective.summary"
  );

  return {
    summary,
    deliverable_type: normalizeString(
      input.objective?.deliverable_type ?? "unspecified",
      "objective.deliverable_type"
    ),
    success_signal: normalizeString(
      input.objective?.success_signal ?? "Task satisfies declared acceptance criteria.",
      "objective.success_signal"
    )
  };
}

export function createTaskEnvelope(intakeInput, options = {}) {
  if (!intakeInput || typeof intakeInput !== "object") {
    throw new Error("Expected intakeInput to be an object");
  }

  const now = isoTimestamp(options.now ? new Date(options.now) : new Date());
  const id = intakeInput.id ?? crypto.randomUUID();

  const taskEnvelope = {
    id: normalizeString(id, "id"),
    title: normalizeString(intakeInput.title, "title"),
    description: normalizeString(intakeInput.description, "description"),
    origin: normalizeOrigin(intakeInput.origin),
    status: "intake_ready",
    timestamps: {
      created_at: now,
      updated_at: now,
      completed_at: null
    },
    status_history: [],
    objective: normalizeObjective(intakeInput),
    constraints: normalizeConstraints(intakeInput.constraints),
    acceptance_criteria: normalizeAcceptanceCriteria(intakeInput.acceptance_criteria),
    parent_task_id: null,
    child_task_ids: [],
    dependencies: [],
    assigned_executor: null,
    required_capabilities: [],
    priority: "normal",
    artifacts: {
      pr_links: [],
      commit_shas: [],
      logs: [],
      outputs: []
    },
    observability: {
      errors: [],
      retries: {
        attempt_count: 0,
        max_attempts: 0,
        last_retry_at: null
      },
      execution_metadata: {
        intake_deferred_fields: [
          "parent_task_id",
          "child_task_ids",
          "dependencies",
          "assigned_executor",
          "required_capabilities",
          "artifacts",
          "observability.errors",
          "observability.execution_metadata"
        ]
      }
    }
  };

  return assertValidTaskEnvelope(taskEnvelope);
}
