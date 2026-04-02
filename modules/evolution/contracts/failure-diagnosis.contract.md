# Failure Diagnosis Contract

Planning contract only. This document defines a reviewable, non-runtime shape for future HEE diagnosis records.

## Purpose

Define a stable diagnosis record that captures:

- what was observed in canonical Harness outcomes
- what is inferred as likely causal explanation
- which concrete records support each claim
- how confident HEE is in each inferred cause

The diagnosis contract is advisory. It cannot mutate task lifecycle, verification outcomes, reconciliation outcomes, or completion authority.

## Record Shape (v1 draft)

```text
FailureDiagnosisV1
  diagnosis_id: string
  taxonomy_version: string            # e.g. "failure-taxonomy.v1"
  diagnosis_taxonomy_key: string      # leaf key from taxonomy version above
  status: draft | needs_review | accepted | rejected | superseded

  scope:
    task_ids: string[]                # canonical task ids
    attempt_ids: string[]             # optional canonical attempt ids
    cluster_key: string | null        # optional recurring-pattern grouping key

  observed_facts: ObservedFact[]      # direct, source-backed facts only
  inferred_causes: InferredCause[]    # hypotheses derived from observed facts
  unresolved_questions: string[]

  summary:
    headline: string
    detail: string

  provenance: ProvenanceRef[]         # task/read-model/timeline/evaluation/trace/review refs

  confidence:
    overall: low | medium | high
    scoring_notes: string

  created_at: timestamp
  created_from: diagnosis_run_id | review_id
  supersedes_diagnosis_id: string | null

ObservedFact
  fact_id: string
  category: lifecycle | verification | reconciliation | evidence | runtime | review
  statement: string
  source_refs: ProvenanceRef[]

InferredCause
  cause_id: string
  statement: string
  cause_type: process | policy | contract | adapter | environment | external_dependency | unknown
  supporting_fact_ids: string[]
  contradicting_fact_ids: string[]
  confidence: low | medium | high

ProvenanceRef
  ref_id: string
  source_type: task_envelope | task_read_model | timeline_event | evaluation_record | trace_record | artifact_record | review_record
  source_identifier: string
  captured_at: timestamp
  notes: string | null
```

## Required Semantics

1. **Observed vs inferred separation is mandatory.**
   - `observed_facts` may only contain source-backed statements.
   - `inferred_causes` may only reference facts by ID; they must not be presented as observed truth.

2. **Taxonomy binding is explicit.**
   - Every diagnosis must include both `taxonomy_version` and `diagnosis_taxonomy_key`.
   - Keys must resolve to a known taxonomy entry for that version.

3. **Provenance is required and auditable.**
   - Every observed fact must include at least one provenance reference.
   - Inferred causes must link to supporting and/or contradicting observed fact IDs.

4. **Confidence is explanatory, not authoritative.**
   - Confidence expresses uncertainty of inference quality.
   - Confidence never authorizes lifecycle changes or completion decisions.

5. **Advisory-only boundary is preserved.**
   - Diagnosis status reflects review workflow only.
   - No diagnosis record can directly mutate canonical task truth.

## Lifecycle For Diagnosis Records (advisory)

- `draft`: generated, not yet reviewed.
- `needs_review`: explicitly queued for human review.
- `accepted`: human accepted diagnosis as useful advisory interpretation.
- `rejected`: human rejected diagnosis.
- `superseded`: replaced by newer diagnosis via `supersedes_diagnosis_id` linkage.

This lifecycle governs diagnosis records only; it is separate from task lifecycle state.

## Initial Taxonomy Requirement

The initial taxonomy is defined in:

- `modules/evolution/diagnostics/failure-taxonomy.v1.md`

Diagnosis records using this contract must reference taxonomy keys from that document until a new version is explicitly introduced.
