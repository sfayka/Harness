# Local Eval Harness

## Status

Design/spec only. This document does not add an executable eval runner.

Addresses: [GitHub issue #313](https://github.com/sfayka/Harness/issues/313)

## Purpose

Define a local eval harness model for skills and delegated workflows.

Harness should help operators answer a practical question:

Did this skill, agent workflow, or delegation path actually get better?

The answer should be local-first, reproducible, understandable by operators, and linked back to canonical Harness inspection surfaces. It should not become a disconnected benchmark world.

## Product Thesis

Local evals should describe real operator workflows in plain English, run against stable fixtures, compare baseline and candidate behavior, and report regressions in operational terms.

The primary user is an operator improving workflows, not an ML researcher tuning a benchmark.

## Target Surfaces

### Skill-level evals

Evaluate whether a reusable skill or instruction package handles a known scenario correctly.

Examples:

- GitHub PR review skill finds actionable comments
- spreadsheet skill preserves formulas and formatting
- repair skill dispatches the correct follow-up prompt

### Delegated workflow evals

Evaluate a multi-step agent workflow.

Examples:

- planner produces executable tasks
- supervisor notices stale work and requests repair
- executor produces GitHub proof and Harness verifies it

### Ingress-to-verification evals

Evaluate the full path from task intake to Harness verification.

Examples:

- desktop agent creates Linear issue
- Harness stores verification contract
- completion claim is rejected
- repair is requested
- corrected claim is accepted

## Eval Spec Shape

A v1 eval spec should be plain-language first and structured second.

Minimum fields:

```text
LocalEvalSpec
  id: string
  title: string
  target_type: skill | delegated_workflow | ingress_to_verification
  target_ref: string
  scenario: string
  fixture_refs: string[]
  expected_outcomes: string[]
  must_pass_checks: string[]
  allowed_variance: string[]
  expected_artifacts: string[]
  expected_trace_properties: string[]
  expected_budget_behavior: string[]
  canonical_surface_refs: string[]
  baseline_run_ref: string?
```

### Scenario

Plain-English description of the operator workflow being evaluated.

Good scenario text names:

- the user-visible goal
- the expected workflow shape
- what evidence should exist
- what failure modes should be caught

### Fixtures

Stable local input bundles.

Fixtures may include:

- task payloads
- seeded Harness store snapshots
- fake GitHub or Linear facts
- expected artifact bundles
- prior eval run outputs

Fixture references must be stable enough for reruns. If the fixture depends on external live systems, the eval must say so explicitly.

### Expected outcomes

Operator-readable success conditions.

Examples:

- "Harness rejects missing PR proof."
- "The workflow preserves handoff lineage after compaction."
- "The budget hard cap escalates to review instead of silently retrying."

### Must-pass checks

Machine-checkable assertions derived from expected outcomes.

Examples:

- final verdict is `verified_done`
- final state is `in_review`
- trace continuity group contains all expected segments
- budget hard cap event is present
- read-model links to the expected artifact id

### Allowed variance

Explicit tolerance for non-deterministic outputs.

Examples:

- model wording may differ
- runtime duration may vary within a threshold
- generated branch suffix may differ
- ordering may vary only where chronology is not meaningful

## Run Model

### Local reproducible run

Each run should record:

- `eval_id`
- `run_id`
- timestamp
- git commit
- target version
- fixture digests
- model/runtime configuration when known
- environment summary without secrets
- produced Harness task IDs
- produced artifacts and trace references
- budget observations when available

### Baseline run

A baseline is a prior accepted run for the same eval spec.

Baseline records should be immutable for comparison. If the baseline itself is wrong, create a new baseline and preserve the old record.

### Candidate run

A candidate is the run being evaluated against the baseline.

Candidate output should be compared against baseline using explicit categories.

## Comparison Model

Comparison output should classify changes into:

- correctness
- evidence quality
- trace continuity
- budget behavior
- runtime anomalies
- artifact completeness
- operator readability

Each category should support:

- improved
- unchanged
- regressed
- inconclusive
- not_applicable

The comparison should lead with a human-readable summary, then provide structured result data for automation.

## Output Surface

### Human-readable summary

The first output should answer:

- what was evaluated
- whether it passed
- what improved or regressed
- what evidence supports the conclusion
- what an operator should inspect next

### Structured result

Minimum shape:

```text
LocalEvalResult
  eval_id: string
  run_id: string
  baseline_run_id: string?
  candidate_run_id: string
  verdict: pass | fail | review_required | inconclusive
  category_results: CategoryResult[]
  harness_refs: HarnessRef[]
  artifact_refs: ArtifactRef[]
  trace_refs: TraceRef[]
  budget_refs: BudgetRef[]
  summary: string
```

## Relationship To Harness Inspection Surfaces

Local eval output must link back to canonical Harness inspection surfaces when present:

- `GET /tasks`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`
- `GET /tasks/<task_id>/evaluations`
- `/reset/*` contract inspection routes for reset-slice evals

Eval output may summarize those surfaces, but it must not replace them.

## Boundary Rules

- Local evals are quality and regression checks, not lifecycle authority.
- Passing an eval does not accept a task as complete.
- Failing an eval does not automatically fail a task.
- Evals may use Harness truth, traces, artifacts, and budget records as inputs.
- Evals must preserve the distinction between local deterministic proof and live external proof.

## Worked Example: Repair Workflow Eval

Scenario:

- seeded task fixture expects GitHub PR proof
- completion claim omits PR
- Harness rejects the claim
- repair workflow is triggered
- corrected claim provides PR, branch, and commit
- Harness accepts completion

Expected checks:

- first verdict is `retryable_invalid_proof`
- repair request is recorded
- final verdict is `verified_done`
- trace continuity links invalid claim, repair request, and corrected claim
- budget does not exceed configured retry cap

## Worked Example: Skill-Level Eval

Scenario:

- a PR-review skill reads a fixture containing review comments
- it must identify actionable feedback and ignore non-actionable commentary
- it must produce a concise plan with file references

Expected checks:

- all blocking comments are classified as actionable
- resolved or praise-only comments are not converted into work
- output includes exact file paths when available
- no completion claim is made

## Related Documents

- [Trace Continuity Model](trace-continuity.md)
- [Execution Budget Model](execution-budget-model.md)
- [Runtime Execution Contract](runtime-execution-contract.md)
- [Verification And Completion Enforcement](verification-and-completion-enforcement.md)
- [Agent API Usage](../api/agent-api-usage.md)
- [Integrations Overview](../integrations/overview.md)
