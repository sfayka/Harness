# Runtime Execution Contract

## Purpose

Define the canonical runtime execution contract for Harness.

Harness is a reliability/control-plane system. The runtime coordinates execution after dispatch, preserves durable in-flight state, records execution events, and feeds normalized execution facts back into the control plane.

The runtime is not the planner, not the dispatcher, and not the verifier.

## Runtime Role

The runtime is responsible for coordinating task execution once a task has been assigned to a worker.

It is responsible for:

- starting execution after a valid assignment exists
- preserving durable in-flight execution state
- receiving and normalizing worker events
- recording execution progress, failures, retries, and stalls
- attaching execution outputs and artifacts back to the task record or linked audit records
- surfacing execution facts to later control-plane decisions

It is not responsible for:

- defining task meaning
- decomposing work
- selecting the executor
- verifying completion correctness
- reconciling external systems of record

## Runtime Boundary Summary

The runtime defines:

- execution coordination
- execution event recording
- progress, stall, and failure tracking
- retry orchestration at execution level

The runtime does not define:

- planning
- executor selection
- task correctness
- artifact-backed completion policy
- reconciliation outcomes

If a question is about whether work has actually started, whether it is still making progress, whether it stalled, or whether it needs another attempt, that is typically runtime-owned.

If a question is about whether the work was the right work, whether completion is trustworthy, or whether the task should be considered done, that belongs outside the runtime contract.

## Preconditions For Execution

Execution may begin only when all of the following are true:

- the input `TaskEnvelope` is schema-valid
- the task is in `assigned`
- `assigned_executor` identifies the current active assignment
- required clarification is absent or resolved
- required dependencies remain satisfied at execution start
- the execution gateway accepts the dispatch request

The runtime must not begin execution merely because a dispatcher selected a worker.

Execution starts only when the runtime has a real execution-start fact from the execution gateway or worker integration.

## Assigned Versus Executing

The distinction between `assigned` and `executing` is strict.

### Assigned

`assigned` means:

- a worker has been selected
- assignment has been recorded
- execution has not yet begun

### Executing

`executing` means:

- the worker or execution gateway has emitted a real start signal
- work is now in flight
- runtime coordination and event tracking are active

The runtime must not collapse these into one state transition.

`dispatch_ready` -> `assigned` is a dispatch decision.

`assigned` -> `executing` is an execution fact.

## Runtime Input Contract

The runtime receives:

- one canonical `TaskEnvelope` in `assigned`
- the normalized execution request from the dispatcher
- executor and workflow substrate context needed to coordinate in-flight work

### Required TaskEnvelope Inputs

The runtime relies on these fields:

- `id`
- `status`
- `assigned_executor`
- `objective`
- `constraints`
- `acceptance_criteria`
- `artifacts`
- `clarification`
- `observability`

The runtime may inspect:

- `dependencies` to ensure no blocking prerequisite changed before start
- `status_history` for prior attempt context
- `origin` for provenance

The runtime must not require planner-only or verifier-only objects as canonical runtime input.

### Execution Request Inputs

The dispatcher or execution gateway should provide a normalized execution request containing:

- task identifier
- selected executor information
- the canonical task payload or allowed projection of it
- dispatch identifier
- attempt or retry context when applicable

The runtime may enrich this with substrate-native details, but those details are not the canonical contract.

## Runtime Output Contract

The runtime output is a stream of auditable execution facts, not a correctness judgment.

It should produce:

- `execution_id`
- `task_id`
- `attempt_id`
- normalized execution events
- task updates derived from those events
- links to produced outputs or artifacts
- retry or stall decisions when policy authorizes them

## Execution Event Semantics

Runtime events must be explicit and reviewable.

The initial execution event family should include:

- `execution_started`
- `progress_reported`
- `output_attached`
- `artifact_attached`
- `execution_failed`
- `execution_succeeded`
- `execution_stalled`
- `execution_timed_out`
- `retry_scheduled`
- `retry_started`
- `execution_canceled`

These names are architecture-level semantics. Exact implementation enums can be finalized later.

### Execution Started

Represents the first trustworthy signal that work actually began.

This event should:

- trigger `assigned` -> `executing`
- record execution start time
- attach execution identifiers needed for later audit

### Progress Reported

Represents a neutral progress fact while work is still in flight.

Examples:

- heartbeat received
- milestone reached inside the worker flow
- partial output produced
- worker status update emitted

Progress events must remain advisory execution facts. They do not change task meaning on their own.

### Output Attached

Represents a non-final execution output attached to the task.

Examples:

- analysis output
- generated document
- intermediate log bundle
- proposed patch summary

Outputs may be useful before completion, but they do not by themselves prove that the task is complete.

### Artifact Attached

Represents an execution artifact becoming available to the task record.

Examples:

- branch reference
- commit reference
- pull request reference
- changed-file evidence

The runtime may attach these artifacts as execution facts, but later verification still decides whether they satisfy completion requirements.

### Execution Succeeded

Represents executor-reported success for an execution attempt.

This event is advisory.

It may support later transition decisions, but it must not be treated as verified completion on its own.

### Execution Failed

Represents an unsuccessful execution attempt.

This event should include:

- failure timestamp
- failure category when known
- failure message or summary
- whether the failure is retryable under policy

### Execution Stalled

Represents an execution that appears in flight but is no longer making expected progress.

Typical triggers include:

- missing heartbeat
- no progress events within policy thresholds
- runtime detects in-flight work that has stopped advancing

Stall is not automatically the same as failure.

It is a runtime finding that may lead to retry, reassignment, blocking, or manual review depending on policy.

### Execution Timed Out

Represents an attempt that exceeded allowed execution time or deadline thresholds.

This is stronger than a generic stall condition because the policy threshold has been crossed explicitly.

### Retry Scheduled / Retry Started

These events represent additional execution attempts.

They must not erase prior attempt history.

Each retry should remain traceable through:

- attempt identifiers
- retry counts
- timestamps
- the reason for retry

### Execution Canceled

Represents runtime cancellation of an in-flight attempt under control-plane direction or policy.

Cancellation of an attempt does not automatically imply top-level task `canceled`; Harness core still applies lifecycle policy.

## Progress Reporting

Partial progress should be represented as execution events and observability facts rather than as implied status changes.

Good progress reporting should answer:

- is work actually in flight
- when was the last known activity
- what outputs or artifacts have appeared so far
- is the task still advancing or has it stalled

Progress should not silently redefine the task's business meaning.

## Failure Reporting

Failures must remain explicit and auditable.

The runtime should distinguish between at least:

- worker execution failure
- startup failure
- timeout
- stall
- infrastructure or transport failure
- cancellation

Failure reporting should preserve:

- failure category
- failure timestamp
- failure summary
- attempt identifier
- whether retry is allowed or recommended by policy

The runtime reports failure facts.

Harness core decides whether the task becomes `failed`, `blocked`, reassigned, or retried.

## Retry Semantics

Retries are runtime-coordinated additional execution attempts against the same task.

Retries should be represented through:

- `observability.retries`
- `status_history` when top-level lifecycle changes occur
- attempt-scoped execution records
- execution events such as `retry_scheduled` and `retry_started`

Retry policy is not invented by the runtime.

The runtime applies the policy given by Harness core or higher-level orchestration rules.

## Stall And Timeout Semantics

Stalls and timeouts must be treated as first-class runtime findings.

The runtime should record:

- when the stall or timeout was detected
- which attempt was affected
- the detection basis such as heartbeat lapse or duration threshold
- what action was taken next

Possible next actions include:

- continue waiting
- schedule retry
- request redispatch
- move the task into a blocked or failed control-plane path
- require manual review

The runtime may detect the issue.

Harness core and dispatcher policy determine the correct consequence.

## Attachment Of Outputs And Artifacts

The runtime may attach outputs and artifacts back to the task through canonical task surfaces.

Typical attachment paths include:

- `artifacts.items`
- execution-related observability metadata
- linked audit records keyed by task and attempt identifiers

The runtime may also record advisory outputs before verification:

- logs
- analysis outputs
- intermediate documents
- artifact references that still require later validation

Attaching an artifact is not the same as verifying that the artifact satisfies completion policy.

## Runtime Interaction With Dispatcher And Workers

### Dispatcher Owns

- selecting the executor
- recording the active assignment
- deciding redispatch or reassignment consequences

### Runtime Owns

- coordinating the in-flight attempt once assignment exists
- tracking execution start, progress, stalls, retries, and failures
- preserving durable attempt records

### Worker Integrations Own

- worker-specific protocol translation
- emitting raw worker events
- returning outputs or failure signals to the runtime

The runtime is the normalizer between raw worker behavior and control-plane execution facts.

## What The Runtime May Not Decide

The runtime must not:

- redefine task structure
- change the planner's decomposition
- select the worker in the first place
- declare artifacts sufficient for completion
- declare reconciliation successful
- treat executor-reported success as final completion

The runtime coordinates execution, but it does not decide whether the work was ultimately correct or complete.

## Auditability Requirements

Runtime records must remain reviewable after the fact.

At minimum, the control plane should preserve:

- execution identifier
- attempt identifier
- active assignment context
- execution start timestamp
- last progress timestamp
- emitted execution events
- attached outputs and artifacts
- failure, stall, timeout, and retry records
- the source that reported each significant execution fact

The goal is that a reviewer can answer:

- when execution actually started
- what happened during the attempt
- whether the attempt stalled, failed, or succeeded
- what outputs or artifacts were produced
- why a retry or redispatch happened later
