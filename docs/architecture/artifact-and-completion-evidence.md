# Artifact And Completion Evidence

## Purpose

Define the canonical model for execution artifacts and completion evidence in Harness.

Harness is a reliability/control-plane system. Executor-reported success is advisory. Completion is only trustworthy when the task's evidence policy is satisfied by verifiable artifacts.

## Design Goals

- support artifact-backed completion
- support multiple artifacts per task
- distinguish evidence from advisory output
- support reconciliation with GitHub and Linear
- preserve auditability over time

## Core Model

TaskEnvelope attaches artifacts under `artifacts`.

`artifacts` contains:

- `items`: canonical artifact records
- `completion_evidence`: the policy and validation state used to decide whether completion may be accepted

## Artifact Types

Supported canonical artifact types:

- `pull_request`
- `commit`
- `branch`
- `changed_file`
- `log`
- `output`
- `review_note`
- `progress_artifact`
- `plan_artifact`
- `handoff_artifact`

These artifact types are broad enough to support code-bearing tasks, advisory tasks, and reconciliation across external systems.

The long-running support artifact types are intentionally distinct from completion evidence:

- `progress_artifact` captures structured progress state across multiple evaluation cycles or execution sessions
- `plan_artifact` captures decomposition, feature lists, or work-plan state that verification may inspect later
- `handoff_artifact` captures session-transition or executor-transition context needed to continue work safely across sessions

## Artifact Record

Each artifact record includes:

- `id`: stable artifact identifier within the task
- `type`: canonical artifact type
- `provenance`: how Harness learned about the artifact
- `verification_status`: whether the artifact is verified, unverified, rejected, or informational
- `repository`: repository identity when applicable
- `branch`: branch identity when applicable
- `changed_files`: changed-file details when applicable
- `external_refs`: references to external systems such as GitHub or Linear

Optional fields provide type-specific details:

- `location`
- `external_id`
- `commit_sha`
- `pull_request_number`
- `review_state`
- `title`
- `description`
- `content_type`
- `captured_at`
- `metadata`

## Type-Specific Required Fields

### pull_request

Required:

- `pull_request_number`
- `repository`
- `branch`
- `provenance`
- `verification_status`

Typical use:

- verify that work was proposed in a repository
- connect GitHub PR state back to task completion

### commit

Required:

- `commit_sha`
- `repository`
- `provenance`
- `verification_status`

Typical use:

- prove a concrete code change exists
- support reconciliation between task state and repository history

### branch

Required:

- `repository`
- `branch`
- `provenance`
- `verification_status`

Typical use:

- capture working branch context even when completion is not yet satisfied

### changed_file

Required:

- `repository`
- `branch`
- `changed_files` with at least one file
- `provenance`
- `verification_status`

Typical use:

- show file-level evidence without requiring a full PR or commit artifact

### log

Required:

- `provenance`
- `verification_status`

Typical use:

- diagnostic evidence
- execution traces

Logs are not sufficient for completion on their own unless a task's evidence policy explicitly allows them.

### output

Required:

- `provenance`
- `verification_status`

Typical use:

- advisory or research deliverables
- generated documents or reports

### review_note

Required:

- `provenance`
- `verification_status`

Typical use:

- approval notes
- manual verification statements
- review commentary

### progress_artifact

Required:

- `provenance`
- `verification_status`

Typical use:

- progress logs that summarize what has been completed so far
- feature or checklist state carried across multiple sessions
- intermediate status snapshots used during later verification or review

These artifacts improve continuity and auditability, but they do not imply completion by themselves.

### plan_artifact

Required:

- `provenance`
- `verification_status`

Typical use:

- structured decomposition output
- feature implementation plans
- reviewable work plans used during later enforcement or manual review

These artifacts document intended execution shape. They are verification inputs, not completion proof by default.

### handoff_artifact

Required:

- `provenance`
- `verification_status`

Typical use:

- session handoff summaries between agent runs
- environment-state notes required to resume long-running work
- executor transition context when work spans multiple sessions or workers

These artifacts preserve continuity across long-running work, but they do not override completion policy or lifecycle enforcement.

## Repository And Branch Identity

Repository identity is represented as:

- `host`
- `owner`
- `name`
- `external_id` optional

Branch identity is represented as:

- `name`
- `base_branch`
- `head_commit_sha` optional

This allows Harness to tie task evidence back to an external repository context without embedding Git provider-specific runtime types.

## Changed Files Representation

Changed files are represented as an array of records containing:

- `path`
- `change_type`
- `previous_path` optional
- `additions` optional
- `deletions` optional

This supports both auditability and later reconciliation with external systems that expose file-level diffs.

## Provenance

Every artifact record must include provenance:

- `source_system`
- `source_type`
- `source_id`
- `captured_by` optional

Provenance is required so Harness can later explain where evidence came from and whether it came directly from an external system, from an executor report, or from a manual verifier.

For long-running artifacts, `metadata` should carry structured continuity details when relevant, such as:

- progress counters or checklist summaries for `progress_artifact`
- plan scope, decomposition revision, or feature list identifiers for `plan_artifact`
- previous session identifiers, next executor identifiers, or resume instructions for `handoff_artifact`

Harness stores these as auditable task artifacts, but keeps the metadata executor-neutral and substrate-neutral.

## Completion Evidence

`artifacts.completion_evidence` is the canonical completion rule state for a task.

It includes:

- `policy`
- `status`
- `required_artifact_types`
- `validated_artifact_ids`
- `validation_method`
- `validated_at`
- `validator`
- `notes`

### Evidence Policy

`policy` may be:

- `deferred`: evidence requirements have not been decided yet
- `required`: completion must be backed by artifacts
- `advisory_only`: outputs may be useful without strong external evidence
- `not_applicable`: evidence is not relevant for this task type

### Evidence Status

`status` may be:

- `deferred`
- `pending`
- `satisfied`
- `insufficient`
- `not_applicable`

## Completion Rules

A task may transition to `completed` only when both the task outcome and the evidence state support it.

Canonical rules:

- if `completion_evidence.policy` is `required`, then `completion_evidence.status` must be `satisfied`
- if `completion_evidence.policy` is `required`, then `validated_artifact_ids` must reference the artifacts used for verification
- if evidence is required but missing, completion must not be accepted
- executor-reported success without evidence is not sufficient for `completed`
- advisory or research tasks may use `advisory_only` or `not_applicable`, but that must be explicit
- progress, plan, and handoff artifacts may inform verification and review, but they are not completion-bearing artifact types in the current contract

## Distinguishing Outcome Classes

### Completed With Evidence

- task reaches `completed`
- `completion_evidence.policy` is `required`
- `completion_evidence.status` is `satisfied`
- validating artifacts are recorded

### Work Attempted Without Evidence

- executor may report success or attempted work
- evidence policy remains unmet
- `completion_evidence.status` is `insufficient`
- task should remain non-complete, typically `blocked` or `failed` depending on policy

### Advisory Or Research Output Only

- task may produce useful outputs without code-bearing artifacts
- `completion_evidence.policy` is `advisory_only` or `not_applicable`
- completion still requires explicit policy alignment, not implicit trust

## GitHub And Linear Reconciliation

The model supports later reconciliation by:

- representing GitHub-native evidence through repository, branch, PR, commit, review, and changed-file records
- allowing external references back to GitHub and Linear identifiers
- separating evidence presence from evidence validation
- making it possible to compare Harness lifecycle state against both structured work state and artifact state

Long-running support artifacts may also be reconciled where applicable, for example when a handoff artifact references a GitHub branch or a Linear issue key. They remain informative inputs unless a later contract explicitly promotes them into completion policy.

## TaskEnvelope Alignment

TaskEnvelope uses this model through:

- `artifacts.items` for canonical artifact records
- `artifacts.completion_evidence` for completion policy and validation state

This keeps completion enforcement inside Harness rather than inside executor reports or workflow runtime state.
