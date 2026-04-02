# Evolution Candidate Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Define the minimum reviewable record for a possible Harness improvement discovered from diagnoses and evidence.

A candidate is an **advisory planning object**. It captures why a proposal may be needed and how a reviewer can inspect provenance before any implementation work is authorized.

## Candidate Shape

```text
EvolutionCandidate
  candidate_id: string
  title: string
  summary: string
  source_diagnosis_ids: string[]
  source_evidence_refs: EvidenceRef[]
  hypothesis: string
  proposal_type: contract_change | policy_change | adapter_change | observability_change | documentation_change | process_change
  target_surfaces: TargetSurface[]
  estimated_risk: low | medium | high
  assumptions: string[]
  open_questions: string[]
  review_state: draft | under_review | approved_for_planning | rejected | parked
  created_at: timestamp
  updated_at: timestamp
```

### Supporting Types

```text
TargetSurface
  area: schema | evaluator_policy | lifecycle_enforcement | read_model | adapter | operator_runbook | docs
  component: string

EvidenceRef
  evidence_type: task_timeline | evaluation_record | reconciliation_summary | verification_summary | artifact | manual_review_note | execution_trace
  reference_id: string
  note: string
```

## Required Semantics

- Must link to at least one diagnosis (`source_diagnosis_ids`) and at least one evidence reference (`source_evidence_refs`).
- Must explicitly identify impacted surfaces (`target_surfaces`) rather than implying hidden or broad mutation authority.
- Must preserve review state independently from delivery/implementation state.
- Must retain provenance to canonical Harness inspection surfaces and historical records.
- Must remain advisory until accepted through normal planning and delivery workflows.

## Explicit Prohibitions

An `EvolutionCandidate` must not be interpreted as authority to:

- mutate runtime task state or policy decisions
- create or apply code changes automatically
- open pull requests automatically
- deploy changes automatically

Candidates are inputs to human review and planning only.

## Relationship To Proposal Contract

A candidate can be promoted into one or more `EvolutionProposal` records after review.

Proposal-level structure is defined in `modules/evolution/contracts/evolution-proposal.contract.md`.
