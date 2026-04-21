# Execution Budget Model

## Status

Design/spec only. This document does not add budget accounting, billing integration, alert delivery, storage, or UI behavior.

Addresses: [GitHub issue #312](https://github.com/sfayka/Harness/issues/312)

## Purpose

Define how Harness should model execution budgets for delegated workflows.

Harness already enforces evidence and lifecycle correctness. That is not enough for production operators. A task can be evidence-backed and still be operationally unsafe if it burns far more time, money, retries, tool calls, or agent fan-out than authorized.

Budget governance is part of operator trust.

## Core Principle

Budget exhaustion can affect orchestration, review, and continuation policy.

Budget exhaustion does not assert completion truth.

## Budget Dimensions

### Model and token spend

Tracks estimated or actual model usage.

Minimum fields:

- provider or model family when known
- input units
- output units
- total cost estimate when available
- source of cost data

### Elapsed runtime

Tracks wall-clock execution time.

Minimum fields:

- started_at
- ended_at or last_observed_at
- elapsed_seconds
- active versus waiting time when the runtime can distinguish them

### Attempts and redispatches

Tracks execution count and repair/retry count.

Minimum fields:

- attempt_count
- retry_count
- redispatch_count
- repair_dispatch_count
- current attempt identifier

### Subagent fan-out

Tracks delegated child work or parallel agent count.

Minimum fields:

- delegated_work_count
- active_subagent_count
- max_concurrent_subagents
- subagent identifiers when available

### Tool and integration spend classes

Tracks expensive or risky tool categories even when precise dollars are unavailable.

Initial classes:

- browser automation
- long-running code execution
- external API calls
- repository mutation
- hosted execution
- file or object storage operations

## Budget Scopes

### Per task

Total authorized budget for the canonical task.

Use when the operator wants one cap for the whole outcome regardless of attempts.

### Per attempt

Budget for one execution attempt.

Use when retry behavior should be bounded independently from the task total.

### Per executor

Budget for a specific executor or executor class.

Use when different executor types have different risk or cost profiles.

### Per project, queue, or policy profile

Budget for a larger operating surface.

Use when many tasks share an operator policy, project budget, or queue-level cap.

This is optional for v1 design and should not block task-level budget semantics.

## Threshold Semantics

### Soft threshold

A soft threshold means the system should warn, annotate, or require an explicit continuation policy.

Allowed consequences:

- append timeline annotation
- record evaluation or runtime warning
- notify operator
- require continuation policy before further automatic retry
- lower priority or restrict fan-out

Soft threshold crossing must be visible, but it does not necessarily stop execution.

### Hard cap

A hard cap means automatic continuation is no longer allowed without explicit policy.

Allowed consequences:

- pause execution
- block the task pending operator decision
- escalate to manual review
- cancel queued retry or redispatch
- fail the attempt if policy marks cap violation terminal

Hard cap crossing must not silently continue.

## Control-Plane Outcomes

Budget events should be projected into canonical surfaces as execution governance facts:

- timeline annotations
- read-model budget summary
- execution attempt metadata
- review request context when escalation occurs
- HEE/local-eval input when analyzing workflow regressions

Budget events should not be projected as verification success or failure by themselves.

Examples:

- token soft threshold crossed: annotate and alert
- runtime hard cap crossed: pause and escalate to review
- retry budget exhausted: stop automatic repair and require operator decision
- tool class cap crossed: block further use of that tool class for the task

## Inspection Surface Requirements

Operators should be able to inspect:

- active budget policy
- consumed budget by dimension
- remaining budget when measurable
- top contributors by attempt, executor, and tool class
- threshold crossings
- actions taken because of each threshold
- whether execution is allowed to continue automatically

## Alerting Semantics

Budget alerts should include:

- task id
- attempt id when applicable
- threshold crossed
- measured consumption
- configured cap
- consequence already taken
- allowed operator choices

Alerts should be explicit operational messages, not hidden evaluator notes.

## Worked Scenario

1. Task `task-456` is assigned to Codex Cloud.
2. Budget policy allows two attempts, 30 minutes elapsed runtime, and one browser automation session.
3. Attempt 1 starts and records model spend, runtime, and one browser tool event.
4. Attempt 1 fails with missing PR evidence.
5. Harness schedules one repair retry.
6. Attempt 2 crosses the soft token threshold.
7. Harness appends a budget warning and alerts the operator, but execution continues because policy allows one soft crossing.
8. Attempt 2 crosses the hard runtime cap.
9. Harness cancels further automatic retry and escalates the task to manual review.
10. Manual review sees budget context alongside execution attempts, evidence state, and reconciliation results.
11. Completion is still decided by verification/reconciliation or explicit review, not by the budget event itself.

## Boundary Rules

- Budget policy influences whether work may continue automatically.
- Budget policy does not decide whether produced work is correct.
- Budget warnings and cap violations must be auditable.
- Budget data must preserve attempt and executor attribution when available.
- Missing budget telemetry should be visible as unknown or unavailable, not treated as zero spend.

## Related Documents

- [Runtime Execution Contract](runtime-execution-contract.md)
- [Operator And Manual Review](operator-and-manual-review.md)
- [TaskEnvelope Contract](task-envelope.md)
- [Codex Cloud Execution](codex-cloud-execution.md)
- [`modules/evolution/contracts/execution-budget.contract.md`](../../modules/evolution/contracts/execution-budget.contract.md)
