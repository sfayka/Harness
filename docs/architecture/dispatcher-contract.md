# Dispatcher Contract

## Purpose

Define the canonical contract for dispatcher behavior in Harness.

Harness is a reliability/control-plane system. The dispatcher is the module that takes planned tasks, decides which worker class should handle them, records that assignment, and initiates execution through the execution gateway.

The dispatcher is not the planner, not the runtime, and not the verifier.

## Dispatcher Role

The dispatcher converts planned task structure into auditable assignment decisions.

It is responsible for:

- selecting an executor type for a dispatchable task
- recording assignment decisions on the canonical task record
- moving tasks through dispatch-related lifecycle states
- initiating execution through the execution gateway
- deciding when reassignment or retry routing is needed under control-plane policy
- preserving auditable assignment history

It is not responsible for:

- decomposing work
- redefining task structure
- executing the assigned work itself
- verifying completion
- reconciling artifacts with GitHub or Linear
- implementing workflow runtime durability

## Dispatcher Boundary Summary

The dispatcher defines:

- assignment
- routing
- dispatch sequencing at the task level
- reassignment policy application

The dispatcher does not define:

- planning
- task decomposition
- runtime execution mechanics
- completion verification
- artifact reconciliation

If a question is about who should do the work and when the task becomes ready to start, it is usually dispatcher-owned.

If a question is about how the worker actually runs, persists, retries internally, or proves completion, it belongs elsewhere.

## Preconditions For Dispatch

Dispatch may begin only when all of the following are true:

- the input `TaskEnvelope` is schema-valid
- the task is in a dispatch-eligible lifecycle state
- required clarification is absent or resolved
- required upstream dependencies are satisfied
- the task is sufficiently defined for executor selection
- no blocking verification or reconciliation condition forbids execution from starting

### Dispatch-Eligible Lifecycle States

The primary dispatch entry state is:

- `dispatch_ready`

Controlled reassignment may also occur from:

- `assigned`
- `blocked`

but only when control-plane policy explicitly allows redispatch or reassignment.

The dispatcher must not begin normal dispatch from:

- `intake_ready`
- `planned`
- `executing`
- `completed`
- `failed`
- `canceled`

### Clarification Preconditions

Dispatch must not proceed if required clarification remains unresolved.

Dispatch is blocked when:

- `clarification.status` is `required`, `requested`, or `answered`
- a required clarification input remains open
- the task is waiting on human or system clarification response

Dispatch may proceed when:

- no `clarification` object is present, or
- `clarification.status` is `resolved`, and
- the task has returned to a dispatch-eligible state

### Dependency Preconditions

Dispatch must respect explicit dependency edges.

Dispatch is blocked when:

- one or more required upstream tasks have not yet reached the dependency's required status
- a checkpoint gate task remains incomplete
- a blocked upstream task prevents safe downstream assignment

The dispatcher must not route around declared dependencies simply because an executor appears available.

### Verification And Reconciliation Preconditions

Dispatch is normally earlier than completion verification, but the control plane may still forbid dispatch if:

- the task is under active manual review
- a prior failed or contradictory execution attempt has not yet been reconciled
- reassignment policy requires human review before another attempt starts

The dispatcher must not override verification or reconciliation policy by starting work anyway.

## Dispatcher Input Contract

The dispatcher receives:

- one canonical `TaskEnvelope` that is ready for dispatch
- optional dispatch policy directives supplied by Harness core
- executor inventory or worker capability facts supplied by integration layers

### Required TaskEnvelope Inputs

The dispatcher relies on these task fields:

- `id`
- `status`
- `objective`
- `constraints`
- `acceptance_criteria`
- `dependencies`
- `required_capabilities`
- `priority`
- `assigned_executor`
- `clarification`
- `observability`

The dispatcher may inspect:

- `origin` for provenance or routing hints
- `artifacts` for prior execution context, but not for completion authority
- `status_history` for prior assignment and failure history

The dispatcher must not require executor-native request shapes as canonical input.

### Optional Dispatch Directives

Harness core may provide directives such as:

- permitted executor classes
- forbidden executor classes
- assignment policy profile
- escalation thresholds
- reassignment rules

These directives constrain dispatch policy, but they do not replace the canonical task contract.

## Executor Selection Semantics

Executor selection must remain explicit and reviewable.

The dispatcher chooses an abstract worker type based on:

- required capabilities
- task type and constraints
- policy restrictions
- executor availability facts
- prior assignment history when reassignment is needed

The dispatcher may choose:

- executor type
- specific executor instance when policy requires it
- assignment reason

The dispatcher must not treat an executor's own self-reporting as the source of truth for whether it is appropriate to receive the task.

## Assignment Recording

Assignment is recorded on the canonical task contract through existing task surfaces rather than a dispatcher-only shadow object.

Primary recording surfaces:

- `assigned_executor`
- `status`
- `status_history`
- `observability.execution_metadata`

### Assigned Executor

`assigned_executor` records the current assignment decision.

It should capture:

- `executor_type`
- `executor_id` when a specific worker instance is selected
- `assignment_reason`

This field represents the active assignment, not the full assignment history.

### Assignment Audit Trail

Assignment history should remain auditable through:

- `status_history` entries such as `dispatch_ready` -> `assigned`
- assignment-related observability metadata
- runtime or registry records linked back to the task

The dispatcher must produce enough assignment evidence that a reviewer can answer:

- who the task was assigned to
- when it was assigned
- why that worker was selected
- whether the task was later reassigned

## Dispatcher Output Contract

The dispatcher output is a structured assignment result, not a freeform narrative.

It should contain:

- `dispatch_id`
- `task_id`
- `dispatch_result`
- `task_update`
- `assignment_record`
- `execution_request`
- `dispatch_notes`

### Dispatch Result

`dispatch_result` should indicate one of:

- assignment created
- dispatch deferred
- dispatch blocked
- reassignment required
- dispatch rejected by policy

### Task Update

Allowed dispatcher-owned task updates include:

- `status` -> `assigned`
- `assigned_executor`
- dispatch-related `status_history` entry
- assignment-related observability updates

The dispatcher may also authorize the transition from `assigned` to `executing` when the execution gateway confirms work has actually started.

The dispatcher must not use the task update to:

- redefine task structure
- modify decomposition relationships
- satisfy completion evidence
- mark the task completed

### Assignment Record

The assignment record should capture:

- assignment identifier
- selected executor type
- selected executor instance if known
- assignment timestamp
- assignment reason
- whether this is a first assignment or reassignment

This record may live in control-plane storage or runtime systems, but it must remain traceable back to the canonical task.

### Execution Request

The dispatcher may produce a normalized execution request for the execution gateway.

That request should include:

- task identifier
- selected executor information
- canonical task payload or allowed projection of it
- dispatch context needed by the execution gateway

The dispatcher defines the assignment decision.

The execution gateway defines the worker-specific protocol translation.

## Lifecycle Semantics

### Dispatch To Assigned

Normal dispatch transition:

- `dispatch_ready` -> `assigned`

This means:

- an executor has been selected
- the assignment has been recorded
- the task is ready to start execution but has not yet started

### Assigned To Executing

Normal execution-start transition:

- `assigned` -> `executing`

This should occur only when the execution gateway or runtime confirms that work has actually begun.

The dispatcher may initiate this transition path, but it must not infer execution start without a real execution-start signal.

### Blocked Dispatch

A task may remain or become `blocked` instead of `assigned` when:

- dependencies are unresolved
- clarification is unresolved
- policy forbids assignment
- no suitable executor is currently permitted or available

The dispatcher must represent this explicitly rather than silently leaving the task in `dispatch_ready`.

### Reassignment

Reassignment is a control-plane decision to replace or supersede a prior assignment.

It may occur when:

- an assigned worker fails to start
- execution stalls and policy allows reassignment
- the original executor is no longer valid for the task
- retry policy requires a new worker selection

Reassignment should:

- update `assigned_executor`
- add a new auditable assignment record
- preserve prior assignment history

Reassignment must not silently erase the fact that the task was previously assigned elsewhere.

## Retries And Redispatch

Retries and redispatch are related but not identical.

### Retry

A retry means the system is attempting the task again after a failed or interrupted attempt.

Retry state should remain visible through:

- `observability.retries`
- `status_history`
- assignment history when a new worker is selected

### Redispatch

Redispatch means the task is being sent back through dispatcher decision-making again.

Redispatch may choose:

- the same executor class
- a different executor class
- the same worker instance
- a different worker instance

Policy for when redispatch is allowed belongs to Harness core.

The dispatcher applies that policy. It does not invent it.

## Dispatcher Interaction With Runtime And Execution Systems

The dispatcher hands work off to the execution gateway and workflow runtime, but it does not become those systems.

### Execution Gateway Owns

- worker-specific protocol translation
- submission to Codex, Claude, or future workers
- normalization of executor events back into control-plane inputs

### Workflow Runtime Owns

- durable orchestration state
- retries, resumes, and timers at runtime level
- persistence of in-flight execution operations

The dispatcher may request execution or reassignment.

The runtime and execution gateway own how that request is actually carried out.

## What The Dispatcher May Not Decide

The dispatcher must not:

- decompose the task into sub-tasks
- redefine dependencies or checkpoint structure
- decide completion correctness
- satisfy artifact evidence requirements
- reconcile GitHub or Linear state
- treat executor-reported success as verified completion

The dispatcher may assign work, but it does not own whether the work was ultimately correct or complete.

## Auditability Requirements

Dispatcher behavior must remain reviewable after the fact.

At minimum, the control plane should preserve:

- dispatch or assignment identifier
- selected executor type and instance when known
- assignment timestamp
- assignment reason
- any reassignment events
- the transition into `assigned`
- the signal that moved the task into `executing`
- retry or redispatch context when applicable

The goal is that a reviewer can answer:

- why this task was routed to this worker
- whether it was reassigned
- when execution actually started
- which component made the assignment decision
