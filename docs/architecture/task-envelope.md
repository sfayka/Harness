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

- intake of validated requests after clarification
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
| `completed` | task satisfied its acceptance criteria and any required completion evidence has been verified by Harness |
| `failed` | task reached a terminal unsuccessful outcome |
| `canceled` | task was intentionally stopped and should not continue |

## Allowed Lifecycle Transitions

Canonical transitions:

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
- `blocked` -> `planned`
- `blocked` -> `dispatch_ready`
- `blocked` -> `assigned`
- `blocked` -> `canceled`

Terminal states:

- `completed`
- `failed`
- `canceled`

`status_history` should capture all non-initial state changes with timestamps and reasons.

For tasks with required completion evidence, transition to `completed` is only valid after `artifacts.completion_evidence.status` reaches `satisfied`.

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

Each dependency contains:

- `task_id`: referenced task
- `dependency_type`: currently `blocks` or `related`
- `required_status`: status the dependency must reach before this task is unblocked

### Execution Routing

Execution routing fields remain abstract so executors can be swapped without changing the contract.

`assigned_executor` includes:

- `executor_type`: abstract worker type
- `executor_id`: specific executor instance, if one is selected
- `assignment_reason`: optional routing explanation

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

- `items`: canonical artifact records such as pull requests, commits, changed files, logs, outputs, and review notes
- `completion_evidence`: the current policy and validation state for deciding whether a task may be treated as complete

Each artifact record may carry:

- artifact type
- repository and branch identity
- changed-file information
- provenance
- external references
- verification status

Completion is not trusted purely because an executor claims success. `artifacts.completion_evidence` is where Harness records whether the evidence requirement is deferred, required, satisfied, insufficient, or not applicable.

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

## Schema Reference

The machine-readable schema lives in [task_envelope.schema.json](../../schemas/task_envelope.schema.json).
