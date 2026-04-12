# OpenClaw Autonomy Supervisor MVP Design

## Goal

Make autonomous OpenClaw-supervised runs feasible without weakening Harness control-plane boundaries.

OpenClaw remains the only human-facing ingress. Harness remains the canonical source of task truth, evidence enforcement, reconciliation, and lifecycle correctness. The MVP should let OpenClaw poll Harness for tasks that need attention because they are stale, blocked, review-gated, or showing invalid execution proof.

## Problem

Harness can already:

- accept canonical tasks and ingress-shaped task submissions
- dispatch work
- validate completion claims
- reconcile repository proof
- expose canonical read-model and timeline surfaces

Harness cannot yet:

- provide a canonical supervision queue for OpenClaw
- tell OpenClaw which tasks need intervention right now
- distinguish between benign inactive tasks and stale active tasks
- surface a bounded next action for retry, clarification, review, or stale investigation

Without that queue, OpenClaw can create or observe tasks but cannot supervise them with canonical Harness truth. That makes autonomous runs fragile and forces orchestration logic back into ingress code.

## Scope

This MVP slice adds one new capability:

- a canonical supervision queue that OpenClaw can poll

The queue will project attention items from existing Harness truth using current read-model fields and timeline data.

## Out Of Scope

This slice does not add:

- live OpenClaw webhooks or long-running subscription transport
- live Linear polling
- a production Codex Cloud executor adapter
- automatic redispatch or mutation from the queue itself
- a new dashboard mutation surface

Those are follow-on autonomy slices.

## Users

- OpenClaw automation loop
- operators validating whether Harness can supervise real work

## Design Principles

1. OpenClaw polls canonical Harness truth instead of rebuilding heuristics client-side.
2. The queue is read-only. It recommends actions; it does not perform them.
3. Attention reasons must map to existing control-plane truth, not worker claims.
4. Staleness must be explicit and deterministic.
5. Queue entries must be auditable back to task id, status, timeline, and summaries.

## Proposed Surface

Add a new read-only endpoint:

- `GET /supervision/queue`

Response shape:

- `generated_at`
- `queue`
  - `task_id`
  - `title`
  - `current_status`
  - `attention_type`
  - `suggested_action`
  - `reason`
  - `last_activity_at`
  - `stale`
  - `review_status`
  - `clarification_status`
  - `failure_state`
  - `retry_eligible`

This is intentionally projection-only and uses existing canonical task/read-model data.

## Attention Types

The first slice should include these attention types:

1. `review_required`
- Trigger when the canonical review gate is active.
- Source truth: `current_status == "in_review"` or `review_summary.status == "requested"`.
- Suggested action: `resolve_review_gate`.

2. `clarification_required`
- Trigger when the task is blocked on missing information.
- Source truth: `clarification_summary.status == "required"`.
- Suggested action: `collect_clarification`.

3. `retryable_failure`
- Trigger when Harness has classified the current state as retryable.
- Source truth: `execution_summary.retry_eligible == true` or `failure_summary.state == "retryable"`.
- Suggested action: `retry_or_redispatch`.

4. `invalid_execution_attempt`
- Trigger when the latest execution attempt failed the executor-proof gate.
- Source truth: `execution_summary.latest_attempt_validation.failure_type == "invalid_execution_attempt"`.
- Suggested action: `request_fresh_proof_or_rework`.

5. `stale_active_task`
- Trigger when an active task has not had canonical activity within a configured threshold.
- Active statuses for the first slice: `planned`, `dispatch_ready`, `assigned`, `blocked`.
- Exclude tasks already covered by review or clarification attention.
- Suggested action: `investigate_staleness`.

## Staleness Model

The queue should derive `last_activity_at` from the latest canonical timeline event timestamp when available. This keeps staleness tied to auditable state transitions, evaluation records, dispatches, clarification, and artifact capture rather than ad hoc task fields.

Default thresholds for the MVP:

- `planned`: 24 hours
- `dispatch_ready`: 2 hours
- `assigned`: 2 hours
- `blocked`: 8 hours

These values are control-plane defaults for unattended supervision tests, not product promises.

## Implementation Units

### `modules/supervision.py`

New read-model style service responsible for:

- building queue entries from `HarnessReadModelService.list_task_read_models()`
- classifying attention type
- computing `last_activity_at`
- computing stale status against default thresholds

### `modules/api.py`

Add:

- `HarnessApiService.get_supervision_queue()`
- `GET /supervision/queue` route in `HarnessApiHandler.do_GET`

### Tests

Add new tests covering:

- direct supervision service classification
- API route behavior
- interaction with existing review, clarification, retryable, and invalid execution states

## Why This Slice First

This is the smallest slice that makes autonomous supervision real:

- OpenClaw gets a canonical queue of “what needs attention now”
- Harness remains the source of truth for why
- no mutation or executor integration is required to prove the supervision boundary

It directly supports the next slices:

- OpenClaw polling loop
- bounded autonomous retry/rework
- real executor integration

## Risks

1. Overlapping attention categories
- Mitigation: strict priority ordering in the queue classifier.

2. False stale positives
- Mitigation: use canonical timeline timestamps and conservative thresholds.

3. OpenClaw re-implementing policy anyway
- Mitigation: include `suggested_action` and `reason` so clients can remain thin.

## Success Criteria

1. A new canonical endpoint returns a queue of tasks that need autonomous or operator attention.
2. The queue is derived entirely from canonical Harness truth.
3. The queue covers review, clarification, retryable failure, invalid proof, and stale active work.
4. The queue is fully test-covered and does not regress existing read-model semantics.
