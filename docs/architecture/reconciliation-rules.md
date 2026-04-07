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
- `task.reconciliation` attempt records when Harness performs operational recovery
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

### Operational Reconciliation Recovery

Conditions:

- execution completed
- a required external artifact for reconciliation is still missing
- Harness has enough repository, branch, and commit context to attempt recovery safely

Meaning:

- the task may move into `reconciling`
- Harness may run a pluggable reconciliation handler for the specific failure class
- every attempt must be captured under `task.reconciliation`
- if recovery succeeds, Harness must return to canonical reevaluation rather than directly declaring completion
- if recovery fails, Harness must escalate the task into explicit `in_review`
- when repository and branch context come from multiple sources, commit identity must come from the same authoritative source or from the execution attempt itself; Harness must prefer a truthful missing commit over a stitched cross-source commit

This is where Harness spends automation before operator attention. Recoverable defects should not require immediate human babysitting, but recovery remains bounded and auditable.

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

When Harness performs an operational recovery such as `missing_pr_after_execution`, it must never create duplicate PRs. It must check for an existing PR by branch and commit before attempting PR creation.

## Failure Class: `missing_pr_after_execution`

### Trigger Condition

This reconciliation handler applies when all of the following are true:

- execution has completed or a completion claim was submitted
- the task has enough repository context to reason about GitHub artifacts
- a commit artifact exists, a commit SHA was supplied, or repository and branch identity are present strongly enough for Harness to recover the branch head SHA before PR lookup
- the required PR artifact is still missing

Harness distinguishes execution from completion. A completion claim without a PR artifact is not enough to reach terminal success when reconciliation policy requires GitHub proof.

Even if a PR artifact is already attached to the task, Harness should only treat that artifact as sufficient when it proves the current run. A stale attached PR must not suppress reconciliation by itself.

Executor-submitted PR artifacts do not become trusted just because a payload marks them `verified`. Completion-claim PR artifacts are candidate facts only until Harness-owned reconciliation upgrades them into canonical verified proof.

This handler only applies once the execution attempt itself is trustworthy enough to reconcile. If the executor reports a reserved/shared branch such as `work`, omits branch identity, supplies a malformed PR URL, or presents stale historical PR evidence as if it were current-run proof, Harness treats that as an execution contract violation before reconciliation starts. `missing_pr_after_execution` is for missing recoverable PR proof on an otherwise valid run, not for malformed or misleading PR proof.

### Bounded Recovery Steps

For `missing_pr_after_execution`, Harness runs a pluggable reconciliation handler with the following bounded sequence:

1. Check that the target branch exists through Git or the GitHub API.
2. If the commit SHA is missing but repository and branch are known, resolve the current branch head SHA through Git or the GitHub API.
3. Validate that the resulting commit SHA is present, non-empty, and resolvable.
4. Bind the current completion claim to the specific execution attempt it references, using the explicit claim `attempt_id` when present rather than whichever attempt happens to be latest.
5. Compare repository, branch, and commit context across `external_facts`, attached artifacts, and execution-attempt metadata. If those sources disagree, stop and record the conflict rather than choosing one implicitly.
6. If repository and branch identity come from execution metadata or normalized external facts, do not let attached artifacts silently backfill a missing commit SHA. Leave commit identity unresolved and continue through the bounded recovery path instead of treating historical artifact state as current-run proof.
7. Query GitHub for candidate PRs by branch.
8. Query GitHub for candidate PRs by commit association.
9. Validate each candidate against the current run context rather than treating branch lookup as success.
10. Treat commit-association lookup as discovery evidence, not current-run proof, unless the PR head still matches the current expected commit or policy explicitly allows weaker matching.
11. When the task has multiple execution attempts, require explicit run linkage to the current attempt rather than relying on task linkage alone.
12. Reject candidates whose PR state is unknown. Missing state metadata is not treated as implicitly open.
13. If exactly one valid current-run PR remains, attach it as a canonical verified artifact and mark reconciliation `resolved`.
14. If only stale or invalid candidates were found, continue to PR creation if it is still safe.
15. If no valid PR exists, create one through the GitHub API, stamp it with Harness task/run linkage markers, read the persisted PR record back from GitHub, and validate that persisted record against current-run policy.
16. If PR creation fails, the created PR cannot be revalidated from persisted state, the branch head SHA cannot be resolved, or ambiguity remains, capture the error and mark reconciliation `failed`.

Every attempt must be recorded under `task.reconciliation`, including the handler name, lookup steps, all candidates found, why each candidate was accepted or rejected, creation result, final status, and any captured error.

The synchronous create response is not sufficient proof on its own. Harness only treats a newly created PR as valid after a read-after-write fetch returns a persisted PR record that still satisfies current-run validation.

### Candidate Validation Policy

For this failure class, Harness distinguishes `artifact exists somewhere` from `artifact proves this run`.

A candidate PR only satisfies reconciliation by default if it passes all of the following checks:

- repository matches the expected repository
- head branch matches the expected current branch exactly
- PR state is acceptable under policy
- head SHA matches the expected commit SHA
- commit association may surface audit candidates, but by default it does not override a head-SHA mismatch
- when the task has multiple execution attempts, the PR must also prove current-run linkage to the active attempt or completion claim

Current default policy is intentionally strict:

- `allow_open_pr_match: true`
- `allow_closed_pr_match: false`
- `require_head_sha_match: true`
- `require_exact_branch_match: true`
- `allow_commit_association_match: true`
- `allow_non_head_commit_association_match: false`
- `escalate_on_ambiguous_match: true`
- `require_run_linkage_for_multiple_attempts: true`
- `require_run_linkage_for_commit_association: true`

Task linkage in the PR title or body is still recorded for auditability, but it is weaker than run linkage. Branch reuse and reruns mean `task exists in this PR somewhere` is not strong enough proof for the current run.

By default, a PR where the current commit merely appears somewhere in history is not accepted as proof for the current run if the PR head no longer matches the expected commit. Harness records that candidate and why it was rejected, then continues to create-or-escalate rather than accepting stale history as present truth.

Harness run linkage uses explicit PR markers for:

- `Harness-Task-ID`
- `Harness-Attempt-ID`
- `Harness-Completion-Claim-ID`
- `Harness-Branch`
- `Harness-Commit-SHA`

This means a branch-only match is not sufficient proof for the current run.

### Idempotency Rule

Repeated reconciliation attempts must not create duplicate PRs.

The handler must always perform PR lookup before PR creation:

- lookup by branch surfaces likely candidates on the expected head
- lookup by commit surfaces candidates that actually correspond to the expected commit
- candidate validation rejects stale, closed, merged, wrong-SHA, wrong-branch, run-unlinked, or otherwise non-current matches
- only the absence of a valid current-run candidate may proceed to PR creation

This keeps retries safe and makes the handler suitable for bounded repeated execution.

### Success Path

If reconciliation resolves the missing artifact:

- Harness attaches the PR URL to task artifacts
- `task.reconciliation` records a resolved attempt
- Harness runs canonical reevaluation
- the task may reach `completed` only if reevaluation accepts the outcome

The reconciliation handler does not authorize terminal success on its own. Tasks only reach terminal success through artifact-backed reevaluation, not execution claims alone.

An attached PR therefore means more than `some PR was found`. It means the PR passed current-run validation policy strongly enough to count as proof for this execution.

### Failure Path

If reconciliation fails or is blocked:

- Harness records the failed attempt and error details under `task.reconciliation`
- the task does not silently remain `completed`
- retryable provider or platform failures move the task to `blocked`
- objective proof-chain contradictions move the task to `failed`
- logical ambiguity, unsupported context, or other unresolved exceptions move the task to `in_review`

`blocked` means progress stopped because the reconciliation environment or provider could not safely complete the repair yet, but no human judgment has been proven necessary.

`failed` means reconciliation proved the execution outcome is terminally unusable. Examples include missing GitHub branches, commits that do not exist, or other objective contradictions that do not require operator interpretation.

`in_review` means safe automation has stopped and human judgment is now required. This is different from `reconciling`, where system repair is still actively running.

### Recoverable And Non-Recoverable Outcomes

Recoverable outcomes for this class include:

- the branch exists, the commit exists, and exactly one current-run PR candidate passes validation
- the branch exists, the commit exists, no PR exists yet, and GitHub accepts PR creation

Non-recoverable or escalation outcomes for this class include:

- the branch cannot be found
- the commit SHA is empty or does not resolve
- `external_facts`, artifacts, and execution metadata disagree about repository, branch, or commit identity
- GitHub lookup returns only historical or otherwise stale PRs
- GitHub lookup returns contradictory, ambiguous, or unusable results
- GitHub refuses or blocks PR creation for a logical or policy reason

Retryable blocked outcomes for this class include:

- GitHub API rate limits, transport failures, or 5xx provider errors
- temporary provider-side permission or availability failures that prevent branch, commit, lookup, or PR creation checks from completing

These outcomes remain specific to `missing_pr_after_execution`. Other reconciliation classes may have different recovery boundaries.

## Failure Class: `missing_commit_after_execution`

### Trigger Condition

This reconciliation handler applies when all of the following are true:

- execution has completed or a completion claim was submitted
- the task already carries a verified current-run PR artifact
- repository and branch identity are coherent enough to resolve current-run GitHub context
- the required commit artifact is still missing

This class is intentionally narrower than `missing_pr_after_execution`. Harness only attempts it when PR truth is already established strongly enough for the current run. If PR proof is missing, weak, stale, or ambiguous, Harness does not use this handler as a shortcut.

### Bounded Recovery Steps

For `missing_commit_after_execution`, Harness runs a pluggable reconciliation handler with the following bounded sequence:

1. Check that the target branch exists through Git or the GitHub API.
2. If commit SHA is missing from current code context, resolve the current branch head SHA through Git or the GitHub API.
3. Validate that the resulting commit SHA is present, non-empty, and resolvable.
4. Confirm that a verified current-run PR artifact is already attached to the task.
5. Attach a verified commit artifact for the resolved SHA.
6. Update completion evidence when commit proof is a required artifact type.
7. Mark reconciliation `resolved` and return to canonical reevaluation.

If branch lookup fails, commit resolution fails, the commit does not exist, or the task does not actually carry a verified current-run PR artifact, Harness records the failed attempt and escalates rather than fabricating commit proof.

### Recovery Boundary

Recoverable outcomes for this class include:

- a verified current-run PR artifact already exists and the commit SHA can be resolved and attached
- branch and commit identity are present already, so commit attachment is mechanical

Escalation outcomes for this class include:

- the branch cannot be found
- commit SHA cannot be resolved from the current branch head
- the resolved commit does not exist
- the attached PR artifact does not actually prove the current run

These are objective contradictions, not review-only ambiguities. By default they terminate this class into task status `failed` rather than `in_review`.

Like other reconciliation handlers, `missing_commit_after_execution` does not authorize terminal success on its own. The task may only reach `completed` if canonical reevaluation accepts the resulting evidence.

## Governed Proofs

The current proof set for `missing_pr_after_execution` shows both sides of the bounded recovery contract:

- [`docs/demo/kno-174-missing-pr-after-execution/README.md`](../demo/kno-174-missing-pr-after-execution/README.md): failure-path proof. This establishes safe escalation when recovery is blocked and the task lands in `in_review` with structured reconciliation evidence.
- [`docs/demo/kno-175-missing-pr-success/README.md`](../demo/kno-175-missing-pr-success/README.md): success-path proof. This establishes successful auto-repair for this failure class, followed by canonical reevaluation to `completed`.

These proofs are intentionally narrow. They prove governed behavior for `missing_pr_after_execution`; they do not prove universal auto-recovery across all reconciliation failures. `missing_commit_after_execution` is implemented, but it is not part of the governed proof bundle yet.

Current implementation maps reconciliation-driven manual review to the explicit `in_review` lifecycle state. A task that requires review must not remain `completed`.

`linear_record_not_found` is intentionally classified as `review_required` rather than an automatic mismatch. The missing record may mean the task reference is unresolved, stale, or ambiguous, and Harness should not guess which contradiction applies without human review.

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
