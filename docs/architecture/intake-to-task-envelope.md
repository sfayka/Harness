# Intake To TaskEnvelope Mapping

## Purpose

Define how intake becomes the first producer of valid `TaskEnvelope` objects in Harness.

This document specifies which fields intake owns, which defaults it must apply, and which fields are intentionally deferred to later modules.

## Intake Responsibility

The intake module accepts a normalized inbound request and produces a schema-valid `TaskEnvelope`.

Intake owns:

- validating required inbound fields
- creating the initial task identifier when one is not supplied
- mapping ingress metadata into `origin`
- setting the initial lifecycle state
- populating all required schema fields with intake-owned values or explicit defaults
- validating the produced envelope against the canonical JSON Schema

Intake does not own:

- decomposition into child tasks
- dependency resolution
- executor selection
- workflow runtime state
- execution artifacts beyond empty initialization

## Inbound Intake Shape

The intake constructor expects an object with these required inputs:

| Field | Required | Notes |
| --- | --- | --- |
| `title` | yes | short task label |
| `description` | yes | human-readable task description |
| `origin.source_system` | yes | upstream system identifier |
| `origin.source_type` | yes | origin category such as `ingress_request` |
| `origin.source_id` | yes | upstream request identifier |
| `acceptance_criteria` | yes | at least one stated completion condition |

Optional inbound fields:

- `id`
- `origin.ingress_id`
- `origin.ingress_name`
- `origin.requested_by`
- `objective.summary`
- `objective.deliverable_type`
- `objective.success_signal`
- `constraints`

## Mapping Rules

### Identity

- `id` uses the inbound `id` if provided
- otherwise intake generates a UUID

### Origin

- `origin` is copied from inbound metadata after normalization
- optional origin fields become `null` when omitted

### Lifecycle

- `status` is always initialized to `intake_ready`
- `timestamps.created_at` and `timestamps.updated_at` are set to the construction time
- `timestamps.completed_at` is set to `null`
- `status_history` starts as an empty array

### Structure

- `title` comes directly from inbound input
- `description` comes directly from inbound input
- `objective.summary` defaults to `description` when no explicit summary is provided
- `objective.deliverable_type` defaults to `unspecified`
- `objective.success_signal` defaults to `Task satisfies declared acceptance criteria.`
- `constraints` defaults to an empty array
- `acceptance_criteria` is normalized and required

### Relationships

These fields are explicitly deferred at intake time:

- `parent_task_id` -> `null`
- `child_task_ids` -> `[]`
- `dependencies` -> `[]`

### Execution

These fields are explicitly deferred at intake time:

- `assigned_executor` -> `null`
- `required_capabilities` -> `[]`
- `priority` -> `normal`

`priority` is initialized rather than omitted because the canonical schema requires it, but intake does not treat this as a dispatch decision.

### Artifacts

Artifacts are initialized empty:

- `pr_links` -> `[]`
- `commit_shas` -> `[]`
- `logs` -> `[]`
- `outputs` -> `[]`

### Observability

Observability is initialized without runtime behavior:

- `errors` -> `[]`
- `retries.attempt_count` -> `0`
- `retries.max_attempts` -> `0`
- `retries.last_retry_at` -> `null`
- `execution_metadata.intake_deferred_fields` lists fields not yet owned by intake

## Deferred Ownership

Fields deferred beyond intake:

| Field Group | Next Owner |
| --- | --- |
| decomposition hierarchy | planner |
| dependencies | planner |
| executor selection | dispatcher |
| executor capability requirements | dispatcher |
| execution logs and outputs | executor integrations |
| non-intake observability metadata | runtime integrations |

## Validation Rule

Every produced envelope must be validated against [task_envelope.schema.json](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/schemas/task_envelope.schema.json) before leaving intake.

If validation fails, intake must reject the envelope rather than emitting a partial or schema-invalid object.
