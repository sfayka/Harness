# Verification And Completion Enforcement

## Purpose

Define the canonical verification and completion enforcement contract for Harness.

Harness is a reliability/control-plane system. Completion is not accepted because an executor reported success. Completion is a control-plane decision made by evaluating runtime facts, artifact evidence, acceptance criteria, and reconciliation results.

Verification is therefore the policy layer that decides whether a task outcome is trustworthy enough to remain completed.

## Verification Role

Verification consumes the facts produced by other modules and applies Harness completion policy to them.

It is responsible for:

- evaluating whether acceptance criteria are satisfied strongly enough for completion
- checking whether required evidence is present and validated
- consuming reconciliation outcomes from GitHub and Linear comparison flows
- classifying completion claims as accepted, blocked, insufficient, mismatched, or review-required
- enforcing lifecycle consequences when completion is not trustworthy
- preserving auditable verification decisions

It is not responsible for:

- planning task structure
- assigning executors
- coordinating runtime execution
- producing the underlying artifacts itself
- redefining external system facts

## Verification Boundary Summary

Verification defines:

- completion acceptance policy
- insufficiency and mismatch handling
- lifecycle consequences of completion decisions
- explainable verification outcomes

Verification does not define:

- task decomposition
- routing or scheduling
- worker execution mechanics
- external connector behavior

If a question is about whether the task should actually be accepted as complete, that is verification-owned.

If a question is about how work was executed or which worker ran it, that belongs elsewhere.

## Verification Inputs

Verification consumes multiple classes of input. No single input is sufficient by itself when policy requires stronger evidence.

### Runtime Facts

Verification consumes normalized runtime facts such as:

- execution attempts
- execution start and end facts
- progress and failure records
- executor-reported success or failure
- outputs and artifacts attached during execution

Runtime facts explain what happened during execution, but they do not decide whether completion should be trusted.

### Artifact And Evidence Records

Verification consumes:

- `artifacts.items`
- `artifacts.completion_evidence`
- validated artifact identifiers
- artifact provenance and verification status

These records determine whether completion has the required evidentiary support.

### Reconciliation Results

Verification consumes reconciliation results that compare Harness state to external systems.

Initial scope includes:

- GitHub artifact facts
- Linear work-state facts
- mismatch categories and reconciliation outcome classes

Verification must treat unresolved reconciliation problems as control-plane inputs, not as optional commentary.

### Acceptance Criteria

Verification consumes the task's declared `acceptance_criteria`.

These criteria define what the task must satisfy in system terms.

Artifacts and reconciliation support completion, but they do not replace task-specific acceptance criteria.

## Core Principle

Executor-reported success is advisory only.

Completion is a policy decision, not a worker claim.

That means:

- runtime may report success
- artifacts may exist
- reconciliation may be partial

and verification may still decide that the task must not remain completed.

## Completion Trust Levels

Verification must preserve a strict distinction between:

- claimed completion
- evidence-backed completion
- reconciliation-verified completion
- accepted completed outcome

### Claimed Completion

An executor or runtime reports that work succeeded.

This is only a claim about execution outcome.

### Evidence-Backed Completion

Required completion evidence is present and validated under the task's evidence policy.

This establishes artifact support, but not yet full trust.

### Reconciliation-Verified Completion

Relevant external systems agree with the task's evidence and outcome, or no blocking mismatch remains.

### Accepted Completed Outcome

Verification has determined that:

- acceptance criteria are satisfied
- evidence policy is satisfied
- no blocking reconciliation problem remains
- no manual review requirement overrides automatic acceptance

Only then may the task be treated as durably completed.

If a task is already marked `completed`, it must not simply remain completed by inertia. It remains completed only if the current verification decision passes under policy.

## Verification Output Contract

Verification output is a structured decision bundle, not a freeform opinion.

It should contain:

- `verification_id`
- `task_id`
- `verification_result`
- `decision_summary`
- `decision_reasons`
- `evidence_evaluated`
- `reconciliation_inputs`
- `task_update`
- `review_requirements` when applicable

### Verification Result

`verification_result` should distinguish at least:

- completion accepted
- insufficient evidence
- external mismatch
- manual review required
- verification deferred
- completion rejected

These names are architecture-level semantics. Exact enum naming can be finalized later.

### Decision Summary

The decision summary should explain in system terms:

- what was evaluated
- which policy conditions passed
- which policy conditions failed
- why the resulting lifecycle consequence was chosen

### Task Update

Allowed verification-owned task updates include:

- preserving `completed` when the outcome is accepted
- moving `completed` back to `blocked`
- moving the task to `failed` when policy determines the outcome is terminally unusable
- recording verification-related status history
- updating completion-evidence validation state when verification is the component performing that policy application

Verification must not use task updates to:

- redefine task structure
- reassign executors
- rewrite runtime history
- invent missing artifacts

## Completion Enforcement Rules

### When Completion May Be Accepted

A task may remain or become `completed` only when:

- acceptance criteria are satisfied strongly enough for policy
- required evidence policy is satisfied
- validated evidence supports the claimed outcome
- reconciliation reveals no blocking mismatch
- no manual review requirement remains outstanding

### When Completion Must Not Be Accepted

Completion must not be accepted when:

- executor-reported success exists without required evidence
- required evidence is insufficient or missing
- external mismatch remains unresolved
- required acceptance criteria are not satisfied
- the system cannot explain why the task should be trusted as complete

### When Completion Should Be Blocked

`blocked` is appropriate when the task may still become trustworthy later if additional facts arrive.

Typical cases:

- missing evidence that may still be attached
- reconciliation mismatch that may still be resolved
- manual review or external confirmation still pending
- acceptance criteria not yet fully demonstrated, but follow-up action could fix that

### When Completion Should Be Failed

`failed` is appropriate when verification determines the completion claim is terminally unusable.

Typical cases:

- wrong repository or wrong branch execution that invalidates the result
- evidence proves the result contradicts the task requirements in a non-recoverable way
- policy determines the task outcome cannot be salvaged by additional evidence or review

### When Manual Review Is Required

Manual review is appropriate when automatic verification cannot safely make the decision.

Typical cases:

- evidence exists but is materially contradictory
- reconciliation sources disagree in a way policy cannot resolve automatically
- acceptance criteria require human judgment that cannot be reduced to current automatic checks

`requires_review` is a verification outcome that moves the task into the explicit `in_review` lifecycle state.

Manual review is non-terminal unless and until a later explicit decision resolves it.

That later decision may:

- accept completion
- keep the task blocked pending more facts
- reject the completion claim
- fail the task if policy determines the outcome is terminally unusable

## Claimed Versus Verified Completion

This distinction must remain explicit.

### Claimed Completion

- worker says the task succeeded
- runtime records the success event
- verification has not yet accepted the outcome

### Verified Completion

- evidence is sufficient
- reconciliation is non-blocking
- verification policy accepts the result

If these collapse into one concept, Harness stops being a reliability layer.

## Insufficient Evidence Versus External Mismatch

Verification must distinguish these outcomes.

### Insufficient Evidence

Means:

- the required evidence policy is not satisfied
- the task may still be fixable by adding or validating evidence

Typical lifecycle consequence:

- remain or become `blocked`

Typical next step:

- attach or validate additional evidence and re-run verification

### External Mismatch

Means:

- evidence or state exists, but external systems contradict the claimed outcome

Typical lifecycle consequence:

- `blocked`
- manual review required
- or `failed` when policy treats the mismatch as terminal

Missing evidence and contradictory evidence are not the same problem.

Typical next step:

- reconcile or resolve the contradiction, then re-run verification

These outcomes must not collapse into the same verification result:

- insufficient evidence means the support is missing or not yet validated
- external mismatch means contradictory facts already exist

## Repeatability And Re-Runnable Verification

Verification is expected to be re-runnable.

It may be run again when:

- new artifacts arrive
- evidence validation status changes
- reconciliation results are updated
- manual review adds new facts
- acceptance criteria interpretation is clarified under policy

The intended direction is:

- verification decisions are explicit, not hidden
- prior verification outcomes remain auditable
- a later rerun may supersede an earlier verification decision when new facts justify it

Verification reruns must not silently erase prior decision history.

### Allowed Effects Of Verification Reruns

A rerun after new evidence or reconciliation data may explicitly:

- preserve `completed` if the outcome remains accepted
- move a previously `completed` task back to `blocked`
- move a previously `blocked` task into an accepted completed outcome
- escalate a previously blocked task to manual review
- resolve a prior manual-review outcome into accepted completion, continued block, or failure
- move the task to `failed` when new facts show the outcome is terminally invalid

What must not happen is silent continuity by default. The latest verification decision must explain why the lifecycle state stays the same or changes.

## Lifecycle Consequences

Verification affects lifecycle state, but only through explicit policy decisions.

### Verified Acceptance

Possible effect:

- task remains `completed` as a trusted completed outcome

This applies only when the current verification run passes.

### Verification Block

Possible effect:

- task moves from `completed` back to `blocked`
- task remains non-complete until evidence or reconciliation improves

### Verification Failure

Possible effect:

- task moves to `failed` when policy treats the outcome as terminally unacceptable

### Review Escalation

Possible effect:

- task remains non-final while a review-required outcome is tracked
- current architecture may represent this through `blocked` plus explicit verification outcome or review metadata

Review escalation is non-terminal by default.

## Runtime Versus Verification

The boundary between runtime and verification must remain strict.

### Runtime Owns

- execution coordination
- execution facts
- attempt records
- advisory success or failure signals

### Verification Owns

- deciding whether completion claims are accepted
- evaluating evidence sufficiency
- consuming reconciliation results
- applying completion policy

Runtime may say "the worker says it finished."

Verification decides whether Harness believes that should count.

## Reconciliation Versus Verification

Reconciliation and verification are related but not identical.

### Reconciliation Owns

- comparing Harness records against GitHub and Linear facts
- classifying mismatch conditions
- reporting whether blocking contradictions exist

### Verification Owns

- using reconciliation results as policy inputs
- deciding lifecycle consequences of those results
- deciding whether completion remains acceptable

Reconciliation provides comparison facts.

Verification applies completion policy to those facts.

## Auditability Requirements

Verification decisions must be explainable in system terms and reviewable later.

At minimum, the control plane should preserve:

- verification identifier
- when verification ran
- which inputs were evaluated
- which policy conditions passed or failed
- which evidence and reconciliation facts were considered
- what lifecycle consequence was chosen
- whether the outcome superseded an earlier verification run

The goal is that a reviewer can answer:

- why completion was accepted or rejected
- what evidence was missing or contradictory
- whether reconciliation was blocking
- why the system chose `completed`, `blocked`, `failed`, or review escalation
