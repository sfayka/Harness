# Operator And Manual Review

## Purpose

Define the canonical operator and manual review contract for Harness.

Harness is a reliability/control-plane system. Human intervention is allowed, but it must occur through explicit, auditable control-plane surfaces rather than informal overrides.

Manual review is therefore a governed decision path, not an escape hatch.

## Manual Review Role

Manual review exists for cases where automatic policy cannot safely decide the next control-plane outcome on its own.

It is responsible for:

- evaluating ambiguous, contradictory, or insufficiently automatable situations
- reviewing task state, evidence, runtime facts, and reconciliation outcomes together
- producing explicit, auditable review decisions
- authorizing lifecycle consequences that remain consistent with state transition policy

It is not responsible for:

- redefining task meaning outside the canonical contract
- bypassing lifecycle enforcement
- erasing prior evidence, history, or verification results
- acting as an undocumented shortcut around planner, dispatcher, runtime, or verification rules

## Core Rule

Human intervention must remain consistent with control-plane policy.

An operator or reviewer may resolve ambiguity, choose among permitted outcomes, or authorize explicit overrides where policy allows.

They may not silently rewrite history or invent an outcome without recording the basis for it.

## When Manual Review May Be Entered

Manual review may be entered when automatic decision-making is unsafe or insufficient.

Initial trigger classes include:

- verification requires human judgment
- reconciliation reveals contradictory external facts
- clarification is deadlocked or cannot be resolved automatically
- runtime behavior is anomalous enough that automatic retry or reassignment is not obviously safe
- an authorized operator explicitly escalates the task

### Verification-Driven Review

Manual review is appropriate when:

- acceptance criteria require judgment that cannot be reduced to current automatic checks
- evidence exists but is contradictory or incomplete in a way policy cannot safely resolve automatically
- completion is claimed, but the system cannot explain whether it should be accepted or rejected

### Reconciliation-Driven Review

Manual review is appropriate when:

- GitHub and Linear disagree materially
- evidence points to conflicting repository, branch, or change facts
- the system cannot safely choose which external fact should control the next lifecycle consequence

### Clarification Deadlock

Manual review is appropriate when:

- clarification has stalled
- required input remains unresolved after normal clarification handling
- a human must decide whether to keep waiting, narrow scope, waive a requirement, or stop the task

### Runtime Anomalies

Manual review is appropriate when:

- retries, stalls, timeouts, or repeated failures leave no obvious automatic next step
- capability mismatch or execution behavior suggests the current path is no longer trustworthy
- automatic redispatch or failure would be too risky without human judgment

### Explicit Operator Escalation

An authorized operator may escalate a task into manual review when:

- policy allows discretionary review
- risk, ambiguity, or external impact justifies human oversight

## Reviewer Input Surface

Manual review must consume an explicit input bundle rather than scattered informal context.

At minimum, the reviewer should be presented with:

- current task state
- task objective, constraints, and acceptance criteria
- artifact and completion evidence state
- reconciliation results and mismatch categories
- runtime facts and attempt history
- clarification state when relevant
- prior review and override history

## Required Review Inputs

### Task State

The reviewer should see:

- current `status`
- relevant `status_history`
- current blocking conditions
- current active assignment when one exists

### Evidence

The reviewer should see:

- `artifacts.items`
- `artifacts.completion_evidence`
- validated artifact identifiers
- any missing or contradictory evidence conditions

### Reconciliation Results

The reviewer should see:

- which systems were compared
- what mismatch categories were triggered
- whether the mismatch appears resolvable or terminal

### Runtime Facts

The reviewer should see:

- attempt history
- execution started/succeeded/failed facts
- stalls, timeouts, cancellations, and retries
- relevant outputs or execution logs when needed

### Prior Review History

The reviewer should see:

- prior review outcomes
- who made them
- when they were made
- whether the current review supersedes an earlier decision

Manual review must never operate as though prior review decisions did not exist.

## Allowed Review Outcomes

Reviewers may choose only from explicit, policy-allowed outcomes.

Initial allowed outcomes include:

- accept completion
- keep blocked
- reject completion
- require clarification
- mark failed
- authorize redispatch
- authorize re-plan
- authorize retry
- cancel the task when policy and operator authority allow it

### Accept Completion

Allowed when:

- the reviewer determines that acceptance criteria, evidence, and reconciliation are sufficient under policy
- the reason completion could not be auto-accepted is now resolved by explicit human judgment

Typical lifecycle consequence:

- preserve or accept `completed`

### Keep Blocked

Allowed when:

- the task is not yet trustworthy enough to move forward or complete
- more facts, clarification, evidence, or external resolution are still needed

Typical lifecycle consequence:

- remain `blocked`

### Reject Completion

Allowed when:

- a completion claim should not be accepted, but the task may still be recoverable

Typical lifecycle consequence:

- move or keep the task in `blocked`
- possibly trigger clarification, redispatch, retry, or replanning depending on policy

### Require Clarification

Allowed when:

- the real blocker is unresolved ambiguity or missing information

Typical lifecycle consequence:

- remain or become `blocked`
- return to clarification handling through the appropriate contract surface

### Mark Failed

Allowed when:

- the reviewer determines the result is terminally unusable under policy

Typical lifecycle consequence:

- move to `failed`

### Authorize Re-Dispatch / Re-Plan / Retry

Allowed when:

- the reviewer concludes the task should continue, but only by re-entering a prior control-plane phase

Typical lifecycle consequence:

- `blocked` -> `dispatch_ready` or `assigned` for redispatch
- `blocked` -> `planned` for replanning
- retry continuation under runtime policy

These are authorization outcomes. The corresponding module still owns the actual transition mechanics.

## Disallowed Reviewer Actions

Reviewers must not:

- directly edit history as if earlier attempts or decisions never happened
- bypass required evidence or reconciliation rules without recording explicit policy justification
- assign a worker outside dispatcher-controlled assignment surfaces
- fabricate artifacts, runtime facts, or reconciliation outcomes
- jump to lifecycle states that are forbidden by state transition policy
- silently reopen terminal states unless a future explicit contract change allows it

Manual review is powerful, but it is not arbitrary.

## Review Decision Recording

Every review decision must be recorded as an auditable control-plane record.

At minimum, a review record should include:

- `review_id`
- `task_id`
- reviewer identity
- reviewer role or authority class
- review timestamp
- review trigger or entry reason
- information evaluated
- chosen outcome
- reasoning summary
- resulting authorized lifecycle consequence
- whether the decision supersedes an earlier review

### Reviewer Identity

The system must record:

- who made the decision
- under what authority or role

Anonymous or unattributed review decisions are not acceptable.

### Reasoning

The reasoning must explain the decision in system terms.

Examples:

- why completion was accepted despite prior review requirement
- why the task remains blocked
- why redispatch is safer than failure
- why the outcome is terminally invalid

### Audit Preservation

Review records must not erase:

- prior review records
- prior verification outcomes
- prior runtime facts
- prior evidence and reconciliation state

If a later review supersedes an earlier one, both must remain auditable.

## Lifecycle Consequences Of Review Outcomes

Manual review must remain consistent with state transition enforcement rules.

### Non-Terminal By Default

Manual review is non-terminal unless it explicitly resolves into a terminal outcome.

This means the normal default after entering review is:

- the task remains non-final
- usually represented as `blocked` plus a review-required outcome

### Completion Acceptance

Review may authorize preserving or accepting `completed`, but only when the reviewer explicitly resolves the review in favor of completion.

`completed` must not survive merely because review happened.

### Block Preservation

Review may keep the task `blocked` when additional evidence, clarification, or external resolution is still needed.

### Failure

Review may authorize `failed` when the reviewer concludes the outcome is terminally unusable.

### Re-Entry To Earlier Phases

Review may authorize re-entry into earlier phases, but only through valid transition paths such as:

- `blocked` -> `planned`
- `blocked` -> `dispatch_ready`
- `blocked` -> `assigned`
- `blocked` -> `intake_ready`

Review does not authorize skipping required control-plane phases.

## Review Versus Verification

Verification and manual review are related but distinct.

### Verification Owns

- automatic completion policy
- evidence and reconciliation evaluation
- automatic lifecycle consequence selection where policy is decisive

### Manual Review Owns

- resolving cases where automatic policy is insufficient or unsafe
- choosing among policy-allowed outcomes when human judgment is required

Manual review should therefore be understood as an explicit escalation path from verification, reconciliation, clarification, runtime anomaly handling, or operator oversight.

## Review Versus Operator Override

Not every operator action is the same as a review outcome.

### Manual Review

Means:

- a reviewer evaluated presented information and chose an explicit decision outcome

### Operator Override

Means:

- an authorized operator directly invoked a policy-allowed control-plane action, such as cancellation or escalation

If an override materially affects task outcome, it should still be recorded with the same level of auditability as review.

## Auditability Requirements

Manual review must remain reviewable after the fact.

At minimum, the control plane should preserve:

- why review was entered
- what information was presented
- who made the decision
- what decision was made
- what lifecycle consequence followed
- whether a later review or verification run superseded it

The goal is that a reviewer of the system can answer:

- why human intervention happened
- whether the intervention stayed within policy
- what evidence or contradiction drove the decision
- how the review changed the task's lifecycle
