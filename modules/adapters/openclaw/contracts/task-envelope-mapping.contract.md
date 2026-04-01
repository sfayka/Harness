# TaskEnvelope To OpenClaw Mapping Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Describe the future projection from canonical `TaskEnvelope` fields into an OpenClaw execution request without making OpenClaw payload shape canonical inside Harness.

## Mapping Principles

- `TaskEnvelope` remains the source of truth.
- Only execution-relevant fields should be projected.
- OpenClaw-specific request fields must stay adapter-local.
- Provenance needed for audit, artifacts, and reevaluation must be preserved.

## Initial Field Sketch

```text
TaskEnvelope.id -> openclaw_request.task_id
TaskEnvelope.objective -> openclaw_request.objective
TaskEnvelope.constraints -> openclaw_request.constraints
TaskEnvelope.acceptance_criteria -> openclaw_request.acceptance_criteria
TaskEnvelope.artifacts -> openclaw_request.expected_artifacts
TaskEnvelope.origin -> openclaw_request.provenance.origin
TaskEnvelope.extensions -> openclaw_request.provenance.extensions_subset
AssignmentContext.executor -> openclaw_request.executor_target
AttemptContext.attempt_id -> openclaw_request.attempt_id
```

## Must Not Be Mapped As Truth

- lifecycle authority
- verification outcomes
- reconciliation decisions
- manual review resolution
- terminal completion acceptance

## Open Questions

- whether OpenClaw needs a richer intermediate task spec than the current `TaskEnvelope` projection
- which extensions are safe to pass through versus retain inside Harness only
- how artifact expectations should be represented for executor ergonomics without weakening verification rules
