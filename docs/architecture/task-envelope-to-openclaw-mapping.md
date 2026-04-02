# TaskEnvelope to OpenClaw Mapping Specification

## Purpose and Boundary

This specification defines the canonical projection from `TaskEnvelope` into a future OpenClaw executor request shape.

The mapping exists to make executor handoff predictable and auditable without changing control-plane authority.

OpenClaw request shape is **not** canonical task truth. Harness remains authoritative for lifecycle, verification, reconciliation, policy enforcement, and completion acceptance. Executor-side fields are an execution-facing projection only.

This document aligns with the `ExecutorAdapter` contract (`docs/architecture/executor-adapter-contract.md`): adapters translate canonical Harness task input into executor-facing payloads and return execution evidence/provenance back to Harness for evaluation.

## Canonical Input Categories Projected from `TaskEnvelope`

Projection is category-based, not vendor-field-driven. Future payload builders should map these categories into OpenClaw request ergonomics while preserving semantics.

1. **Task identity and routing context**
   - canonical task identifier
   - external references needed to correlate execution
   - run-scoped correlation IDs for traceability

2. **Objective and work intent**
   - summary / objective
   - detailed description
   - intended deliverable statement

3. **Acceptance and done conditions**
   - acceptance criteria
   - explicit completion expectations the executor should attempt to satisfy

4. **Constraints and execution guardrails**
   - policy-aligned constraints
   - environment/tooling restrictions relevant to execution behavior

5. **Contextual references and dependencies**
   - repository/workspace context
   - linked tickets/issues/docs needed for execution
   - dependency references required for the work to be actionable

6. **Artifact expectations**
   - expected artifact categories (for example: code changes, test outputs, links)
   - evidence expectations that can be collected during execution

Only categories needed for execution should be projected; control-plane-only state must remain Harness-owned.

## Harness-Only Fields and Semantics (Never Executor-Owned Truth)

The following remain authoritative in Harness and must not be treated as executor truth:

- lifecycle state and lifecycle history
- transition policy and transition authorization
- verification decisions and verification status
- reconciliation outcomes (including mismatch/contradiction handling)
- manual review requirements, gates, and decisions
- accepted completion vs failure authority
- policy decisions for deferred/blocked/review-required outcomes
- append-only evaluation history and audit semantics

Executor claims (including “done”, “success”, or status-like summaries) are advisory signals only.

## Mapping Rules

## 1) Forward directly

Forward canonical content when semantically equivalent and execution-relevant:

- objective/description/acceptance intent
- explicit constraints and references
- execution correlation identifiers

## 2) Transform for executor ergonomics

Transformation is allowed only when it is representational (not semantic mutation), such as:

- formatting structured criteria into executor instruction blocks
- renaming fields to match adapter schema
- splitting/combining textual context for token-budget or UX ergonomics

Any transformation must preserve source provenance and recoverable canonical meaning.

## 3) Omit when non-execution or policy-internal

Do not project fields that would misrepresent control-plane authority, including:

- lifecycle decision state
- policy adjudication details not needed to execute work
- internal evaluation-only bookkeeping

## 4) Preserve provenance

Projection and execution output must preserve enough provenance to reconstruct:

- which canonical task revision drove execution
- which projected categories were sent
- correlation between emitted events/artifacts and canonical task identity
- adapter/executor identity and version metadata

## 5) Never flatten into executor truth

Do not flatten control-plane semantics into executor-owned status fields.

Examples:

- executor “completed” must not directly set Harness `completed`
- executor confidence/claims must not override verification/reconciliation outcomes
- executor omission of evidence must not silently become acceptance

## Output and Provenance Expectations

OpenClaw-shaped execution outputs must provide executor evidence and traceability inputs, not authoritative lifecycle outcomes.

Minimum categories expected back from execution:

1. **Execution events / traces**
   - timestamped event stream or equivalent trace checkpoints
   - stage-level progress/error signals with correlation IDs

2. **Artifact references**
   - stable references to produced artifacts (commits, logs, files, URLs, outputs)
   - artifact metadata sufficient for later verification/reconciliation

3. **Executor metadata**
   - executor identity (adapter + executor)
   - run identifier(s), attempt/retry identifiers
   - relevant runtime/version info

4. **Provenance fields for Harness evaluation**
   - source task ID and task-revision correlation
   - mapping/projection version identifier (or equivalent schema/version marker)
   - immutable linkage between reported outputs and originating execution run

Harness consumes these outputs as evidence inputs for canonical reevaluation. They do not directly finalize lifecycle state.

## Explicit Non-Goals

This document does **not**:

- implement payload builders or runtime wiring
- validate concrete OpenClaw requests
- expand `TaskEnvelope` schema to fit executor ergonomics
- change lifecycle semantics or policy enforcement
- delegate completion authority to executor status fields

## Related Architecture References

- `docs/architecture/task-envelope.md`
- `docs/architecture/executor-adapter-contract.md`
- `docs/architecture/openclaw-executor-adapter.md`
- `docs/architecture/runtime-execution-contract.md`
- `docs/architecture/verification-and-completion-enforcement.md`
- `docs/architecture/reconciliation-rules.md`
