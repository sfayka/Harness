# Failure Diagnosis Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Describe the minimum shape of a future HEE diagnosis record for recurring failures or degraded outcomes.

## Sketch

```text
FailureDiagnosis
  diagnosis_id: string
  task_ids: string[]
  attempt_ids: string[]
  observed_outcome: string
  diagnosis_taxonomy_key: string
  summary: string
  evidence_refs: EvidenceRef[]
  trace_refs: TraceRef[]
  contributing_factors: string[]
  unresolved_questions: string[]
  confidence: low | medium | high
  created_at: timestamp
  created_from: diagnosis_run_id | review_id
```

## Required Semantics

- Must reference canonical task or attempt identifiers.
- Must preserve which evidence and traces support the diagnosis.
- Must distinguish observed facts from inferred causes.
- Must remain advisory and reviewable.
- Must not mutate lifecycle state or task truth directly.

## Open Questions

- whether diagnoses are task-scoped, attempt-scoped, or cluster-scoped by default
- how much taxonomy should be enum-driven versus free-form
- whether confidence is qualitative, numeric, or both
