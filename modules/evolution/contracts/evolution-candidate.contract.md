# Evolution Candidate Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Describe the minimum shape of a future HEE proposal record for a possible Harness improvement derived from diagnoses and evidence.

## Sketch

```text
EvolutionCandidate
  candidate_id: string
  source_diagnosis_ids: string[]
  title: string
  proposal_type: contract_change | policy_change | adapter_change | observability_change | documentation_change
  target_surface: string
  rationale: string
  expected_benefit: string
  risks: string[]
  required_reviewers: string[]
  supporting_evidence_refs: EvidenceRef[]
  status: draft | under_review | accepted | rejected | parked
  created_at: timestamp
```

## Required Semantics

- Must link back to one or more diagnoses or equivalent evidence sources.
- Must state the target surface explicitly instead of implying a hidden mutation path.
- Must preserve review status separately from implementation status.
- Must remain advisory until accepted through normal planning and delivery channels.
- Must not authorize autonomous code changes, PR generation, or deployment.

## Open Questions

- whether candidate status belongs inside Harness storage or only in planning systems
- whether proposal types should be broader or narrower
- how candidate-to-GitHub-issue linkage should be represented
