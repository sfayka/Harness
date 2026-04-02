# Failure Taxonomy v1 (Planning)

Status: planning taxonomy for future HEE diagnosis outputs.

Taxonomy keys classify likely failure modes for recurring analysis. They do not decide task lifecycle state or completion outcomes.

## Design Rules

- Keys are stable and versioned.
- Keys describe inferred causal class, not raw lifecycle status.
- Keys are advisory labels and must be supported by observed facts + provenance.
- New keys must preserve backward-readable history by bumping taxonomy version when semantics change.

## Key Format

`<domain>.<category>.<specific_mode>`

Example: `verification.evidence.missing_required_artifact`

## Domains and Initial Keys

### 1) `verification`

- `verification.evidence.missing_required_artifact`
- `verification.evidence.artifact_unreadable`
- `verification.evidence.artifact_nonconforming`
- `verification.proof.insufficient_completion_evidence`

### 2) `reconciliation`

- `reconciliation.external_fact.contradiction_with_github`
- `reconciliation.external_fact.contradiction_with_linear`
- `reconciliation.external_fact.record_not_found`
- `reconciliation.mapping.identifier_mismatch`

### 3) `execution`

- `execution.runtime.timeout`
- `execution.runtime.crash_or_unhandled_error`
- `execution.runtime.stall_without_progress`
- `execution.environment.dependency_or_tool_unavailable`
- `execution.environment.infrastructure_instability`

### 4) `workflow`

- `workflow.spec.requirements_ambiguous`
- `workflow.spec.scope_conflict`
- `workflow.review.manual_review_required_unresolved`
- `workflow.review.repeated_rejections`

### 5) `policy`

- `policy.enforcement.invalid_lifecycle_transition_attempt`
- `policy.enforcement.unauthorized_completion_claim`
- `policy.enforcement.reconciliation_gate_not_satisfied`

### 6) `ingress`

- `ingress.contract.task_envelope_validation_failed`
- `ingress.contract.missing_required_fields`
- `ingress.adapter.vendor_payload_translation_error`

## Required Pairing With Diagnosis Contract

For each diagnosis:

1. Choose exactly one primary taxonomy key.
2. Keep observed facts independent from key selection.
3. Represent uncertainty through inferred-cause confidence and unresolved questions.
4. If no key fits, use `workflow.spec.scope_conflict` only as temporary fallback and mark taxonomy extension needed.

## Non-Goals

- defining automated remediation policies
- implementing key-assignment algorithms
- replacing human review decisions
