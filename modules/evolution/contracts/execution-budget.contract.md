# Execution Budget Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Define the minimum budget facts future runtime, review, local eval, and HEE surfaces need in order to reason about delegated workflow cost and runaway execution risk.

Budget records are governance facts. They can influence whether execution continues automatically, but they do not decide whether work is complete.

## Design Principles

1. Budget consumption must be attributable to task, attempt, executor, and tool class when known.
2. Soft and hard thresholds must have explicit control-plane consequences.
3. Missing budget telemetry must be represented as unknown, not treated as zero.
4. Budget exhaustion may escalate to review or block continuation, but verification remains completion authority.
5. Budget records must preserve provenance to runtime events, traces, artifacts, or external billing sources.

## Minimum Fields

```text
ExecutionBudgetPolicy
  policy_id: string
  scope_type: task | attempt | executor | project | queue | operator_policy
  scope_id: string
  dimensions: BudgetDimension[]
  thresholds: BudgetThreshold[]
  effective_at: timestamp
  expires_at: timestamp?
  source_system: string
  source_record_id: string?
  schema_version: string

BudgetDimension
  dimension_type: model_spend | token_usage | elapsed_runtime | attempt_count | retry_count | redispatch_count | subagent_fanout | tool_class_usage
  unit: string
  soft_limit: number?
  hard_limit: number?
  unknown_behavior: allow_with_annotation | require_review | block

BudgetLedgerEntry
  entry_id: string
  policy_id: string
  task_id: string
  attempt_id: string?
  executor_id: string?
  trace_segment_id: string?
  continuity_group_id: string?
  dimension_type: string
  unit: string
  quantity: number?
  quantity_status: measured | estimated | unknown
  tool_class: string?
  source_system: string
  source_record_id: string
  recorded_at: timestamp
  schema_version: string

BudgetThresholdEvent
  event_id: string
  policy_id: string
  task_id: string
  attempt_id: string?
  threshold_type: soft | hard
  dimension_type: string
  consumed_quantity: number?
  configured_limit: number?
  action_taken: annotate | alert | pause | block | escalate_to_review | cancel_retry | fail_attempt
  reason: string
  recorded_at: timestamp
  source_system: string
  source_record_id: string?
  schema_version: string

BudgetAlertRecord
  alert_id: string
  threshold_event_id: string
  task_id: string
  attempt_id: string?
  recipient_type: operator | reviewer | system_queue
  channel: dashboard | timeline | webhook | email | chat | local_console
  message: string
  allowed_operator_choices: string[]
  delivered_at: timestamp?
  delivery_status: pending | delivered | failed | suppressed
  schema_version: string
```

## Scope Requirements

### Task-scoped budgets

Task-scoped budgets must aggregate all attempts and retries for the task.

They should answer:

- how much total budget was authorized
- how much has been consumed
- whether automatic continuation is still allowed

### Attempt-scoped budgets

Attempt-scoped budgets must isolate one concrete execution run.

They should answer:

- whether the current attempt is still inside allowed limits
- whether this attempt consumed disproportionate budget
- whether follow-up retry is still allowed

### Executor-scoped budgets

Executor-scoped budgets must identify the executor or executor class that consumed budget.

They should answer:

- which executor spent the budget
- whether one executor class is causing runaway cost
- whether future dispatch should choose a different execution path

## Threshold Requirements

### Soft thresholds

Soft threshold events must record:

- threshold crossed
- measured or estimated consumption
- action taken
- alert or annotation emitted when policy requires one
- whether automatic continuation remains allowed

### Hard caps

Hard cap events must record:

- cap crossed
- action taken
- whether the task is blocked, paused, or escalated
- alert or review request emitted as the visible operator surface
- what operator decision is required before continuation

Hard cap violations must not silently continue.

## Alert Requirements

Budget alerts must be explicit operator-facing records when policy requires operator awareness or intervention.

They should answer:

- which threshold crossed
- how much was consumed
- what limit was configured
- what action Harness already took
- what choices remain available to the operator or reviewer
- whether alert delivery succeeded or failed

An alert delivery failure must be visible as an operational fact. It must not erase the threshold event or allow automatic continuation that policy already blocked.

## Provenance And Linkage Requirements

Budget records should link to:

- `task_id`
- `attempt_id` when known
- `trace_segment_id` when spend is tied to a trace segment
- `continuity_group_id` when spend spans replay/resume/handoff lineage
- runtime events that observed the spend
- external billing or provider records when available
- review records if budget exhaustion triggered review

Missing linkage should be explicit unresolved provenance.

## Boundary Rules

- Budget records are not completion evidence by themselves.
- Budget exhaustion does not prove work failed; it proves automatic continuation is no longer allowed under policy.
- Budget policy must not bypass verification, reconciliation, or manual review.
- Budget telemetry failures must not be hidden.
- Budget summaries may feed HEE/local eval analysis, but advisory outputs remain separate from lifecycle truth.

## Related Documents

- `docs/architecture/execution-budget-model.md`
- `docs/architecture/runtime-execution-contract.md`
- `docs/architecture/operator-and-manual-review.md`
- `docs/architecture/local-eval-harness.md`
