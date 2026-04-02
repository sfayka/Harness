# Evolution Proposal Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Define the advisory proposal record generated from a reviewed evolution candidate.

A proposal is still non-authoritative: it packages a concrete change recommendation, review requirements, and decision trail while preserving the rule that implementation must proceed through normal repository and governance workflows.

## Proposal Shape

```text
EvolutionProposal
  proposal_id: string
  candidate_id: string
  proposal_type: contract_change | policy_change | adapter_change | observability_change | documentation_change | process_change
  target_surfaces: TargetSurface[]
  problem_statement: string
  recommendation: string
  expected_benefits: string[]
  potential_risks: string[]
  mitigations: string[]
  decision_inputs: DecisionInput[]
  reviewers_required: string[]
  decision_state: proposed | in_review | accepted | rejected | superseded | deferred
  decision_notes: string
  tracking_links: TrackingLink[]
  created_at: timestamp
  updated_at: timestamp
```

### Supporting Types

```text
TargetSurface
  area: schema | evaluator_policy | lifecycle_enforcement | read_model | adapter | operator_runbook | docs
  component: string

DecisionInput
  input_type: diagnosis | evidence | prior_decision | incident | operator_feedback
  reference_id: string
  rationale_excerpt: string

TrackingLink
  system: linear | github_issue | github_pr | doc
  identifier: string
  url: string
```

## Required Semantics

- Must retain a direct lineage to its source candidate (`candidate_id`).
- Must preserve evidence and diagnosis provenance via `decision_inputs`.
- Must express proposal type and target surfaces at planning level before implementation begins.
- Must keep decision status (`decision_state`) explicit and auditable.
- Must keep acceptance of a proposal distinct from implementation completion.

## Explicit Prohibitions

An `EvolutionProposal` must not grant direct runtime mutation authority.

Specifically, proposal acceptance alone must not:

- modify `TaskEnvelope` instances in-flight
- change evaluator, verifier, reconciliation, or lifecycle outcomes
- bypass canonical API submission/reevaluation paths
- auto-generate or auto-merge code changes
- auto-deploy policy or runtime configuration

Accepted proposals only authorize humans to begin normal planning/delivery work in external systems.

## Review Transition Expectations

- `proposed` -> `in_review` requires an explicit reviewer handoff.
- `in_review` -> `accepted` or `rejected` requires an explicit decision record.
- `accepted` proposals remain advisory artifacts until implemented through normal issue/PR/release workflows.
