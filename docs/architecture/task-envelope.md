# TaskEnvelope Contract

## Purpose

TaskEnvelope is the canonical contract for structured work inside Harness.

It is the single source of truth for task-shaped work flowing through intake, planning, assignment, execution, and completion. Every module may project, enrich, or synchronize a TaskEnvelope, but no module should redefine its core meaning.

## Design Principles

- implementation-agnostic
- substrate-neutral
- executor-neutral
- explicit lifecycle semantics
- clear separation between business state and runtime observations

## Scope

TaskEnvelope is designed to support:

- intake of requests, including tasks that must pause for clarification before safe execution
- structured planning and decomposition
- dependency tracking
- execution routing
- artifact attachment
- lifecycle transitions
- operational observability

TaskEnvelope does not define:

- user-facing conversation state
- substrate-specific checkpoint state
- executor-native payload formats

## Canonical Shape

At the top level, a TaskEnvelope contains:

- identity
- origin
- lifecycle
- structure
- relationships
- execution routing
- artifacts and outputs
- observability

## Top-Level Fields

| Field | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | string | yes | stable task identifier |
| `title` | string | yes | short task label |
| `description` | string | yes | human-readable task description |
| `origin` | object | yes | where the task came from |
| `status` | enum | yes | current lifecycle state |
| `timestamps` | object | yes | canonical lifecycle timestamps |
| `status_history` | array | no but preferred | audit trail of state changes |
| `objective` | object | yes | intended outcome and deliverable shape |
| `constraints` | array | yes | conditions or limits that must be respected |
| `acceptance_criteria` | array | yes | conditions required for task completion |
| `parent_task_id` | string or null | yes | parent task reference if this task is decomposed from another |
| `child_task_ids` | array | yes | direct child tasks created from this task |
| `dependencies` | array | yes | upstream task relationships that affect execution readiness |
| `assigned_executor` | object or null | yes | current routing decision |
| `required_capabilities` | array | yes | executor capabilities needed for the task |
| `priority` | enum | yes | relative scheduling priority |
| `artifacts` | object | yes | canonical execution artifacts and completion evidence state |
| `clarification` | object | no | canonical missing-information and clarification tracking state |
| `observability` | object | yes | retries, errors, and execution metadata |
| `extensions` | object | no | explicitly non-canonical extension surface for future modules |

## Lifecycle States

TaskEnvelope uses the following canonical states:

| State | Meaning |
| --- | --- |
| `intake_ready` | task has entered Harness and is ready for normalization, clarification, or planning |
| `planned` | task has been decomposed or otherwise defined enough for routing |
| `dispatch_ready` | task is sufficiently defined and ready for executor selection |
| `assigned` | task has an executor selected but execution has not yet started |
| `executing` | executor has started work |
| `blocked` | task cannot currently proceed because of an unmet dependency, missing input, or external blocker |
| `completed` | task satisfied its acceptance criteria and has a provisional completed outcome pending successful reconciliation where reconciliation is required |
| `failed` | task reached a terminal unsuccessful outcome |
| `canceled` | task was intentionally stopped and should not continue |

## Allowed Lifecycle Transitions

Canonical transitions:

- `intake_ready` -> `blocked`
- `intake_ready` -> `planned`
- `planned` -> `dispatch_ready`
- `planned` -> `blocked`
- `planned` -> `canceled`
- `dispatch_ready` -> `assigned`
- `dispatch_ready` -> `blocked`
- `dispatch_ready` -> `canceled`
- `assigned` -> `executing`
- `assigned` -> `blocked`
- `assigned` -> `failed`
- `assigned` -> `canceled`
- `executing` -> `completed`
- `executing` -> `blocked`
- `executing` -> `failed`
- `executing` -> `canceled`
- `completed` -> `blocked`
- `blocked` -> `intake_ready`
- `blocked` -> `planned`
- `blocked` -> `dispatch_ready`
- `blocked` -> `assigned`
- `blocked` -> `executing`
- `blocked` -> `canceled`

Terminal states:

- `failed`
- `canceled`

`status_history` should capture all non-initial state changes with timestamps and reasons.

Allowed transitions are not sufficient by themselves. Each transition must also satisfy ownership and precondition rules enforced by the relevant control-plane module or authorized actor.

For tasks with required completion evidence, transition to `completed` is only valid after `artifacts.completion_evidence.status` reaches `satisfied`.

`completed` must be treated as provisional until required reconciliation succeeds. If reconciliation later detects a blocking mismatch, the task may move back to `blocked` rather than remaining permanently completed.

`completed` is preserved only when verification policy accepts the outcome. Executor-reported success, evidence attachment, or reconciliation in isolation are not enough by themselves.

`blocked` is a lifecycle state, not a root cause. Clarification, external dependencies, and reconciliation failures may all use `blocked`, but they must be distinguished by the relevant contract fields rather than inferred from the state name alone.

State movement is policy-enforced. Executor-reported events may supply inputs, but they do not independently authorize lifecycle transitions such as `assigned` -> `executing` or `executing` -> `completed`.

Manual review is an explicit control-plane function, not an informal override path. Review outcomes must remain auditable and must still respect state transition enforcement rules.

## Field Semantics

### Origin

`origin` records how the task entered Harness.

Required fields:

- `source_system`: upstream system or control-plane producer
- `source_type`: kind of origin such as request, decomposition, retry, or manual intervention
- `source_id`: upstream identifier

Optional fields:

- `ingress_id`: ingress-specific identifier
- `ingress_name`: ingress role label such as OpenClaw
- `requested_by`: actor or system that initiated the work

### Objective

`objective` explains what the task is trying to accomplish without binding it to a specific executor.

Fields:

- `summary`: concise statement of the intended outcome
- `deliverable_type`: output shape such as code change, document, analysis, or configuration
- `success_signal`: plain-language description of what successful completion means

### Constraints

Each item in `constraints` should describe a condition the task must respect.

Fields:

- `type`: category such as technical, policy, dependency, or scope
- `description`: constraint text
- `required`: whether violating the constraint invalidates completion

### Acceptance Criteria

Each item in `acceptance_criteria` defines a condition Harness can use to evaluate completion.

Fields:

- `id`: stable criterion identifier within the task
- `description`: condition text
- `required`: whether the criterion is mandatory

### Relationships

Relationship fields distinguish hierarchy from scheduling dependencies.

- `parent_task_id` and `child_task_ids` define decomposition structure
- `dependencies` define execution prerequisites

Planner-created sub-tasks and checkpoint tasks should attach through these same fields rather than through planner-only relationship objects.

Each dependency contains:

- `task_id`: referenced task
- `dependency_type`: currently `blocks` or `related`
- `required_status`: status the dependency must reach before this task is unblocked

When a task is blocked because another task or external system must finish work first, `dependencies` remains the primary representation. Clarification should not be used to represent ordinary upstream dependency waits.

Checkpoint and validation gates should generally be represented as explicit planned child tasks with dependencies, not as implicit planner notes.

### Execution Routing

Execution routing fields remain abstract so executors can be swapped without changing the contract.

`assigned_executor` includes:

- `executor_type`: abstract worker type
- `executor_id`: specific executor instance, if one is selected
- `assignment_reason`: optional routing explanation

This field records the current active assignment chosen by the dispatcher. Assignment history should remain auditable through `status_history` and observability surfaces rather than being overwritten without trace.

`assigned_executor` must not be used as a historical ledger. It answers "who is actively assigned now," while assignment history lives elsewhere.

`required_capabilities` is a list of capability identifiers such as:

- `code_editing`
- `documentation`
- `repo_analysis`
- `testing`

`priority` is one of:

- `critical`
- `high`
- `normal`
- `low`
- `backlog`

### Artifacts

Artifacts are product-facing outputs and verification evidence attached to the task, not substrate checkpoints.

`artifacts` contains:

- `items`: canonical artifact records such as pull requests, commits, changed files, logs, outputs, review notes, progress artifacts, plan artifacts, and handoff artifacts
- `completion_evidence`: the current policy and validation state for deciding whether a task may be treated as complete

Each artifact record may carry:

- artifact type
- repository and branch identity
- changed-file information
- provenance
- external references
- verification status

Completion is not trusted purely because an executor claims success. `artifacts.completion_evidence` is where Harness records whether the evidence requirement is deferred, required, satisfied, insufficient, or not applicable.

Verification consumes this evidence state but remains a distinct control-plane decision layer. Evidence presence and completion acceptance must not collapse into one concept.

Long-running support artifacts such as `progress_artifact`, `plan_artifact`, and `handoff_artifact` are first-class task artifacts. Harness preserves them for auditability and may use them as verification or review inputs, but they are not completion-bearing by default in the current contract.

### Completion Trust Levels

Harness must keep these concepts separate:

- `executor-reported success`: a worker claims the task succeeded
- `artifact-backed evidence`: the task has artifacts that satisfy the declared evidence policy
- `reconciliation-verified completion`: Harness has compared its internal state against external systems such as GitHub and Linear and found no blocking mismatch

These are not interchangeable.

- executor-reported success is advisory
- artifact-backed evidence is necessary for evidence-driven completion
- reconciliation-verified completion is what makes a completed state durable

### Clarification

`clarification` is the canonical surface for missing, ambiguous, or incomplete information that prevents safe progress.

It is optional because many tasks do not require clarification. When present, it distinguishes information gaps from other blocked conditions without changing the top-level lifecycle model.

`clarification` includes:

- `status`: clarification phase such as `required`, `requested`, `answered`, or `resolved`
- `blocking_reason`: whether the task is blocked by missing information, ambiguous information, or an outstanding human or system response
- `resume_target_status`: the status the task should return to once clarification is resolved
- `required_inputs`: the required or optional inputs Harness is tracking
- `questions`: clarification questions that have been sent or recorded
- `responses`: clarification answers attached to the task

These meanings must remain distinct rather than collapsing into one generic “clarification happened” flag:

- missing information: unresolved required inputs are absent or incomplete
- ambiguous information: multiple plausible interpretations remain
- awaiting human response: clarification was requested and the task is waiting on a person to answer
- resolved clarification: the missing or ambiguous information has been satisfied or explicitly waived and the task can resume safely

Use `clarification` when:

- a required input is missing
- supplied information is ambiguous
- provided information is incomplete enough that progress would rely on guessing
- the task is explicitly waiting on a human or upstream system to answer a clarification request

Do not use `clarification` when:

- the task is blocked by an ordinary dependency on another task
- the task is blocked by artifact or reconciliation mismatch
- the task is paused for executor capacity or scheduling reasons

Clarification states must not authorize silent guessing. If a required input is unresolved, the task should remain `blocked` or otherwise non-progressing until the missing information is supplied, waived by policy, or the task is canceled.

`clarification` may be attached when the task is first entering Harness or later after execution has already begun. The contract supports both by allowing clarification to coexist with `intake_ready`-to-`blocked` and `executing`-to-`blocked` transitions, and by recording the intended `resume_target_status`.

Resolved clarification must not erase history. The `clarification` object should retain the prior `required_inputs`, `questions`, and `responses` records so the task remains auditable after it resumes.

### Observability

Observability captures operational information without redefining business state.

`observability` contains:

- `errors`
- `retries`
- `execution_metadata`

`execution_metadata` is for neutral runtime facts such as:

- attempt counts
- last heartbeat timestamp
- queue name
- scheduling hints
- assignment and dispatch correlation identifiers when needed for auditability
- execution and attempt correlation identifiers when needed for auditability
- last execution progress timestamp when tracked as a neutral runtime fact

It must not store substrate-native execution graphs, workflow classes, or framework objects.

## Business State Versus Runtime State

Business state:

- `status`
- `timestamps`
- `status_history`
- `objective`
- `constraints`
- `acceptance_criteria`
- `parent_task_id`
- `child_task_ids`
- `dependencies`
- `assigned_executor`
- `artifacts`

Runtime observations:

- `observability.errors`
- `observability.retries`
- `observability.execution_metadata`

This distinction matters because Linear and Harness business logic should reason over business state, while substrates and executors contribute runtime observations.

## Module Expectations

### Intake

- creates initial TaskEnvelope instances
- sets `origin`, `objective`, initial `constraints`, and initial `status`

### Planner

- enriches `child_task_ids`, `dependencies`, and decomposition-related fields
- transitions work through `planned` to `dispatch_ready`

### Dispatcher

- updates `assigned_executor`, `required_capabilities`, and `priority`
- moves work from `dispatch_ready` to `assigned`

### Executor Integrations

- contribute logs, outputs, and execution observations
- do not redefine task status semantics outside the canonical lifecycle

### Verification

- evaluates `artifacts.items` and `artifacts.completion_evidence`
- determines whether a completion transition is evidence-backed
- rejects terminal completion when required evidence is missing or insufficient
- reconciles task state against external systems such as GitHub and Linear before preserving or changing terminal lifecycle state

### Reconciliation

- compares Harness task state with system-of-record state and artifact state
- classifies mismatches instead of collapsing them into generic failure
- may keep a task completed, move it to blocked, or mark it as requiring review depending on mismatch severity and evidence policy

## Schema Reference

The machine-readable schema lives in [task_envelope.schema.json](../../schemas/task_envelope.schema.json).
