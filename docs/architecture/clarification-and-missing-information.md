# Clarification And Missing Information

## Purpose

Define how Harness represents tasks that cannot safely proceed because required information is missing, ambiguous, or incomplete.

Harness is a reliability/control-plane system. It must not silently guess when required inputs are absent or unclear.

## Core Rule

If required information is unresolved, Harness must represent that explicitly and prevent unsafe progress.

Clarification is therefore part of the control-plane contract, not a conversational convenience.

## What Counts As Clarification

Clarification applies when the task lacks enough trustworthy information to proceed.

This includes:

- missing required inputs
- ambiguous instructions with multiple plausible interpretations
- incomplete task definitions that would force the system to invent missing details
- explicit waits for human or upstream-system answers to clarification questions

This does not include:

- normal task dependencies
- executor capacity delays
- artifact validation failures
- reconciliation mismatches with GitHub or Linear

Those are separate causes that may also result in `blocked`, but they are not clarification.

## Canonical Representation

Clarification is represented through two layers:

- top-level task lifecycle state
- the optional `clarification` object on `TaskEnvelope`

### Lifecycle State

Harness uses `blocked` as the lifecycle state when clarification prevents safe progress.

This is intentional:

- `blocked` says the task cannot proceed
- `clarification` says why it cannot proceed and what information is needed

Harness does not need a separate top-level `clarification` lifecycle enum if the cause is modeled explicitly.

## Clarification Object

The `clarification` object records the missing-information contract for the task.

### Fields

- `status`
- `blocking_reason`
- `resume_target_status`
- `required_inputs`
- `questions`
- `responses`
- `requested_at`
- `resolved_at`
- `requested_by`
- `resolution_summary`

### Clarification Status

| Status | Meaning |
| --- | --- |
| `not_required` | no clarification is currently needed |
| `required` | Harness has identified unresolved required information, but a question has not yet been sent or recorded |
| `requested` | clarification questions have been issued and the task is waiting on input |
| `answered` | responses have been attached, but the task has not yet been re-normalized and cleared to resume |
| `resolved` | clarification has been satisfied or explicitly waived and the task may return to its prior flow |

### Blocking Reason

`blocking_reason` distinguishes why clarification exists:

- `missing_information`
- `ambiguous_information`
- `waiting_on_human_input`
- `waiting_on_system_input`

This prevents “blocked” from becoming a vague catch-all.

## Clarification Modes Must Stay Distinct

The clarification object must preserve separate meanings for separate situations.

### Missing Information

Use when required information is absent or too incomplete to proceed safely.

Typical shape:

- `clarification.status`: `required` or `requested`
- `clarification.blocking_reason`: `missing_information`
- one or more `required_inputs` with `need_type: missing` or `need_type: incomplete`

### Ambiguous Information

Use when information exists, but multiple materially different interpretations remain plausible.

Typical shape:

- `clarification.status`: `required` or `requested`
- `clarification.blocking_reason`: `ambiguous_information`
- one or more `required_inputs` with `need_type: ambiguous`

### Awaiting Human Response

Use when Harness has already asked a person for clarification and is now waiting on that answer.

Typical shape:

- `clarification.status`: `requested`
- `clarification.blocking_reason`: `waiting_on_human_input`
- at least one open question in `clarification.questions`
- `requested_at` recorded

### Resolved Clarification

Use when the missing or ambiguous information has been satisfied or explicitly waived by policy and the task is safe to resume.

Typical shape:

- `clarification.status`: `resolved`
- `resolved_at` recorded
- `resume_target_status` identifies where work should resume
- prior question and response records remain attached

These modes should not be flattened into a single generic clarification bucket.

### Resume Target

`resume_target_status` records where the task should return once clarification is resolved.

Typical values:

- `intake_ready` when the task must be re-normalized
- `planned` when planning can resume
- `dispatch_ready` when routing was paused for missing detail
- `assigned` or `executing` when work was already in progress and clarification interrupted it

This allows Harness to pause and later resume without inventing a new lifecycle family.

## Required Vs Optional Information

Harness must distinguish required inputs from helpful but optional context.

Each entry in `clarification.required_inputs` carries:

- an identifier
- a label and description
- whether the input is required
- the need type
- whether the input is still open, provided, or waived

Only unresolved required inputs should block progress.

Optional inputs may still be requested, but they should not force the task into a blocked clarification path unless policy explicitly says they are required for correctness.

## Ambiguous Vs Incomplete

Harness must distinguish ambiguous tasks from incomplete tasks.

### Ambiguous

Information exists, but multiple interpretations are still plausible.

Examples:

- “update the docs” without identifying which docs
- “ship the fix” when multiple candidate fixes exist

This should be represented with `need_type: ambiguous`.

### Incomplete

Information is partially present but still insufficient to proceed safely.

Examples:

- a repo is named but no target branch is given
- a feature is requested but no acceptance criteria exist

This should be represented with `need_type: incomplete`.

### Missing

Required information is absent entirely.

Examples:

- no repository is identified
- no objective is supplied

This should be represented with `need_type: missing`.

## Clarification Questions And Responses

Questions and responses must be attached to the task rather than hidden in transient chat context.

### Questions

Each question records:

- a stable ID
- the prompt
- the linked missing-information item when applicable
- its status
- when it was asked
- who it was asked to and through which channel when known

### Responses

Each response records:

- a stable ID
- the linked question or input when known
- who responded
- when the response was received
- the response content
- the source system or reference when applicable

This is necessary for auditability and later replay.

## Lifecycle Semantics

### Entering Clarification

A task should enter clarification handling when:

- required information is missing
- instructions are ambiguous enough that multiple materially different implementations are plausible
- available information is incomplete enough that progress would require guessing
- an in-flight task encounters a missing detail that prevents safe continuation

Typical transition:

- current lifecycle state -> `blocked`
- `clarification.status` -> `required` or `requested`

### Waiting On Human Input

When Harness has already issued a question and is waiting on a person to answer:

- task state should generally remain `blocked`
- `clarification.status` should be `requested`
- `clarification.blocking_reason` should be `waiting_on_human_input`

### Waiting On System Input

If clarification depends on another system providing facts rather than a human answering:

- task may still be `blocked`
- `clarification.blocking_reason` should be `waiting_on_system_input`

This is distinct from a normal dependency on another task’s lifecycle.

### Receiving A Response

When a response arrives:

- the response should be attached to `clarification.responses`
- the relevant input and question records should be updated
- `clarification.status` may move to `answered`

`answered` does not automatically mean execution can resume. The task still needs re-evaluation against the required inputs.

### Resolving Clarification

Clarification is resolved only when:

- required inputs are satisfied or explicitly waived by policy
- no unsafe ambiguity remains
- the task is safe to resume

Then:

- `clarification.status` -> `resolved`
- `resolved_at` is recorded
- the task may move from `blocked` back to `resume_target_status`

Clarification may begin at intake time or later during execution. The same contract applies in both cases. What changes is the `resume_target_status`.

## Distinguishing Clarification From Other Blocked States

### Blocked Due To External Dependency

Use `dependencies` and normal blocked semantics.

Do not use `clarification` unless the blocker is truly missing information.

### Blocked Due To Missing Information

Use:

- task state `blocked`
- `clarification` present
- `clarification.blocking_reason` set appropriately

### Waiting On Human Input

This is a specific clarification case:

- human answer needed
- question has been sent or recorded
- task remains non-progressing until response is evaluated

## Auditability And Retention

Resolved clarification must not silently erase the fact that clarification occurred.

- `required_inputs` should remain on the task after resolution
- `questions` and `responses` should be treated as append-only audit records in normal operation
- if a question is superseded or canceled, mark its status rather than deleting it
- resolution should add `resolved_at` and `resolution_summary`, not remove the earlier evidence

Future implementations may add stronger immutability guarantees, but the architecture already requires clarification history to remain auditable.

### Advisory Missing Context

If context would be useful but is not required for correctness:

- do not force clarification blocking
- capture it as optional input or note if needed

## Policy Implications

- Harness must never proceed by silent assumption when a required input is unresolved.
- Executors should receive clarified tasks or explicit acknowledgment that optional context was waived.
- Clarification history must remain auditable.
- Resumed tasks must not discard the fact that clarification occurred.

## Relation To TaskEnvelope

This document defines the semantics behind the `clarification` object on `TaskEnvelope`.

The goal is to make missing-information handling explicit without conflating it with:

- planner logic
- dispatcher logic
- runtime checkpointing
- external dependency management
