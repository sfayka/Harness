# Reconciliation Rules

## Purpose

Define how Harness reconciles internal task state with external systems of record and artifact systems.

Harness is a reliability/control-plane system. A task is not trustworthy merely because an executor reported success or because one external system looks consistent in isolation. Harness must compare internal lifecycle state, evidence state, and external system state and then represent any mismatch explicitly.

Completion is provisional until reconciliation passes.

## Initial Reconciliation Scope

The initial reconciliation scope is:

- GitHub for code-bearing execution evidence
- Linear for structured work state

These systems are sufficient to establish the first public version of reconciliation semantics without committing to connector implementation details.

## Systems And Roles

### Harness

- owns the canonical task lifecycle
- owns evidence policy and completion enforcement
- decides how mismatches affect task state

### GitHub

- provides artifact facts such as pull requests, commits, branches, reviews, and changed files
- is the source of truth for code-bearing evidence, not for task lifecycle policy

### Linear

- provides the source-of-truth record for structured work state
- is authoritative for issue and project tracking facts, not for completion evidence by itself

## What Is Compared

Harness reconciliation compares:

- internal lifecycle state in `TaskEnvelope`
- `artifacts.items`
- `artifacts.completion_evidence`
- Linear task state and identifiers
- GitHub artifact facts such as repository, branch, commit, pull request, and review state

The goal is to detect when the systems tell incompatible stories about the same task.

## Canonical Reconciliation Inputs

### Harness Inputs

- task `status`
- task `timestamps`
- `artifacts.completion_evidence`
- validated artifact identifiers
- repository and branch context captured in artifacts

### GitHub Inputs

- repository identity
- branch identity
- commit presence
- pull request presence
- review state
- changed-file evidence

### Linear Inputs

- work item identifier
- work item state
- ownership and assignment facts when relevant
- whether the task is represented as active, blocked, done, or canceled

## Reconciliation Principles

- completion claims are advisory until reconciled
- missing evidence is distinct from contradictory evidence
- mismatches must be classified explicitly
- reconciliation results must remain auditable
- external systems inform control-plane decisions but do not replace Harness lifecycle policy

## Completion Trust Model

Harness must preserve a strict distinction between three different concepts:

### Executor-Reported Success

- a worker claims that it completed the task
- this is a claim about execution, not proof of correctness
- by itself, this must not be treated as completion

### Artifact-Backed Evidence

- the task has the required artifacts attached and validated under `artifacts.completion_evidence`
- this establishes that evidence exists
- by itself, this is still not the same as reconciled completion

### Reconciliation-Verified Completion

- Harness has compared its internal task state, artifact evidence, GitHub facts, and Linear facts
- no blocking mismatch remains
- this is the condition that allows a completed state to be treated as trustworthy and durable

These layers must not collapse into one concept.

- executor-reported success without evidence is insufficient
- evidence without reconciliation is still provisional
- only reconciliation-verified completion should be treated as fully trusted

## Reconciliation Outcome Classes

### Verified Completion

Conditions:

- Harness task state is `completed`
- required completion evidence is satisfied
- GitHub and Linear facts agree with the completed outcome

Meaning:

- the task may remain completed as a trusted outcome
- the control plane has enough evidence to trust the terminal state

### Claimed Completion

Conditions:

- an executor or upstream component reports success
- Harness has not yet reconciled that claim with evidence and external systems

Meaning:

- the task must not be treated as fully verified yet
- this is weaker than artifact-backed evidence
- the task may remain `executing` or move into a non-terminal review phase in future implementations
- current architecture should treat this as non-final until reconciliation succeeds

### Missing Evidence

Conditions:

- completion evidence policy is `required`
- required artifacts or validated artifact IDs are missing or insufficient

Meaning:

- the task must not remain `completed`
- the task should typically remain `blocked` or require manual review depending on policy

This is distinct from claimed completion:

- claimed completion means success was reported
- missing evidence means the reported success is not supported by the required artifacts

### External Mismatch

Conditions:

- Harness believes completion is satisfied
- at least one external system reports facts that contradict that state

Examples:

- Linear says the task is still active while Harness believes it is completed
- GitHub evidence referenced by the task cannot be found or does not match the recorded identifiers

Meaning:

- the task cannot be considered fully reconciled
- the mismatch must be represented explicitly and surfaced for audit
- a previously completed task may need to move back to `blocked` or into a review-required state

### Wrong-Repo Or Wrong-Branch Execution

Conditions:

- evidence exists, but the repository or branch identity does not match the task's expected execution context

Examples:

- commit exists in a different repository
- pull request exists on an unexpected branch
- changed files are attached to the wrong codebase context

Meaning:

- completion evidence is invalid for the task as recorded
- the task should not remain completed
- this is stricter than missing evidence because contradictory evidence exists

### Advisory Output Only

Conditions:

- task evidence policy is `advisory_only` or `not_applicable`
- output exists without strong external artifact requirements

Meaning:

- absence of GitHub-style evidence is not automatically a mismatch
- reconciliation still checks consistency with declared policy

## Mismatch Categories

Harness should recognize, at minimum, the following mismatch categories:

- `missing_required_artifact`
- `missing_validated_artifact`
- `github_artifact_not_found`
- `linear_record_not_found`
- `linear_state_conflict`
- `github_review_conflict`
- `wrong_repository`
- `wrong_branch`
- `changed_files_conflict`
- `completion_without_reconciliation`
- `evidence_policy_conflict`

These category names are architecture-level semantics. Exact enum naming can be finalized later in implementation contracts.

## How Mismatches Affect Lifecycle State

The key rule is:

- `completed` is not irrevocable
- `completed` is only durable after required reconciliation passes
- if reconciliation later fails, Harness may move the task back to `blocked` or mark it as requiring review

### Task May Remain Completed

Allowed only when:

- completion evidence policy is satisfied
- reconciliation does not reveal a blocking mismatch
- external facts do not contradict the task's completed state

### Task Should Become Blocked

Typical when:

- required evidence is missing
- external systems are temporarily inconsistent
- additional human or system action is needed before correctness can be re-established

`blocked` is appropriate when progress can resume once the mismatch is resolved.

This includes tasks that were previously marked `completed` but later found to be unreconciled or contradictory.

### Task Should Require Manual Review

Typical when:

- evidence exists but conflicts materially with task expectations
- GitHub and Linear disagree in ways that policy cannot resolve automatically
- the system cannot safely choose between multiple contradictory facts

Manual review is a reconciliation outcome, not a substitute for explicit lifecycle semantics. Future implementation may represent this through a dedicated review flag or mismatch record while preserving the underlying task state.

For current architecture purposes, `requires_review` should be treated as an explicit reconciliation outcome even if it is not yet a first-class lifecycle enum in `TaskEnvelope`.

### Task May Become Failed

Appropriate when:

- reconciliation demonstrates that the execution result is unusable
- the wrong repository or wrong branch was used
- the mismatch is terminal rather than resolvable through follow-up action

## Relationship To Completion Evidence

Reconciliation depends on `artifacts.completion_evidence` but is not identical to it.

- completion evidence asks whether the right artifacts exist and have been validated
- reconciliation asks whether Harness, GitHub, and Linear are mutually consistent about the task outcome

Executor-reported success is earlier than both:

- it is an input claim that may trigger evidence collection and reconciliation
- it must not be treated as either evidence satisfaction or reconciled completion

Completion is trustworthy only when both are satisfied.

A task may therefore:

- reach `completed`
- later become `blocked`
- or require review

if reconciliation reveals that the completion claim was not actually trustworthy.

## Auditability Requirements

Reconciliation must support later audit by preserving:

- which systems were compared
- which facts were checked
- which mismatch category was triggered, if any
- whether the mismatch was resolved automatically or required review

This issue does not require schema expansion yet, but future implementation should store reconciliation outcomes explicitly rather than hiding them in unstructured logs.

## Alignment With TaskEnvelope

Current TaskEnvelope alignment:

- `artifacts.items` carries the evidence facts that GitHub reconciliation depends on
- `artifacts.completion_evidence` carries the completion-evidence policy and validation status
- lifecycle semantics in `status` remain Harness-owned

If future automation requires explicit reconciliation records in the schema, they should be added as targeted control-plane contract changes rather than inferred from executor output.
