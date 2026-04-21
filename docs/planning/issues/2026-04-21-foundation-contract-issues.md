# Foundation Contract Issues Plan

## Source Issues

- [#311 Define trace continuity model for replay, compaction, and handoff](https://github.com/sfayka/Harness/issues/311)
- [#312 Define execution budget model with spend caps and operator alerting](https://github.com/sfayka/Harness/issues/312)
- [#313 Design a local eval harness for skills and delegated workflows](https://github.com/sfayka/Harness/issues/313)

## Recommended Order

1. Define trace continuity first.
2. Define execution budget governance second.
3. Define the local eval harness third.

That order keeps the dependency chain clean. Budget records need attempt, executor, and trace attribution. Local evals need both continuity and budget semantics if they are going to compare delegated workflows instead of only checking final text output.

## Implementation Plan

### Issue #311: Trace continuity

Add a planning architecture document that defines:

- `trace_segment_id`
- `continuity_group_id`
- replay, retry, resume, compaction, handoff, and review relationships
- continuity-preserving artifact expectations
- read/query requirements for operators
- boundary rules that keep trace lineage separate from completion truth

Update the trace requirements contract so future runtime and HEE work has explicit fields to target.

### Issue #312: Execution budget model

Add a planning architecture document and evolution contract that define:

- budget dimensions for model spend, tokens, runtime, attempts, retries, fan-out, and tool classes
- task, attempt, executor, project, queue, and operator-policy scopes
- soft threshold and hard cap semantics
- alert content and control-plane consequences
- review inputs when budget exhaustion blocks automatic continuation

Budget governance should control whether work may continue automatically. It must not decide whether produced work is correct.

### Issue #313: Local eval harness

Add a planning architecture document and concrete eval examples that define:

- plain-English eval specs with stable fixture references
- baseline and candidate run records
- regression categories for correctness, evidence quality, trace continuity, budget behavior, runtime anomalies, artifact completeness, and operator readability
- output shape that leads with an operator summary and keeps structured results available for automation
- links back to canonical Harness inspection surfaces

Local evals are quality checks. They are not task lifecycle authority.

## Deliverables In This PR

- `docs/architecture/trace-continuity.md`
- `docs/architecture/execution-budget-model.md`
- `docs/architecture/local-eval-harness.md`
- `modules/evolution/contracts/execution-trace-requirements.contract.md`
- `modules/evolution/contracts/execution-budget.contract.md`
- `docs/evals/README.md`
- `docs/evals/examples/repair-workflow.eval.md`
- `docs/evals/examples/pr-review-skill.eval.md`

## Deferred Work

- storage schema
- ingestion APIs
- runnable eval CLI
- dashboard UI
- alert delivery integrations
- migration of existing trace or budget data

Those should come after the contracts are reviewed and accepted.
