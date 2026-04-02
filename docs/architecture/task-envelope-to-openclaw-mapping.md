# TaskEnvelope to OpenClaw Mapping Specification

## Purpose

This document defines the canonical mapping from Harness `TaskEnvelope` inputs into a future OpenClaw executor request shape.

The mapping exists to make future OpenClaw execution integration implementation-guiding while preserving Harness as the control-plane authority.

Specifically, this mapping ensures:

- Harness canonical contracts remain defined by `TaskEnvelope` and control-plane policy.
- OpenClaw request ergonomics can evolve without redefining Harness truth.
- Executor reports remain advisory inputs to verification and reconciliation, not accepted completion.

This specification is subordinate to and aligned with the executor adapter boundary described in:

- [`docs/architecture/executor-adapter-contract.md`](./executor-adapter-contract.md)
- [`docs/architecture/openclaw-executor-adapter.md`](./openclaw-executor-adapter.md)

The `ExecutorAdapter` contract remains authoritative for the boundary; this document provides the OpenClaw-specific mapping profile for that boundary.

## Canonical Input Categories Projected from TaskEnvelope

The adapter may project only execution-relevant categories from `TaskEnvelope` and dispatch context.

### 1) Task identity

Projected for correlation and traceability:

- canonical `task_id`
- execution/attempt identifier assigned by Harness dispatch/runtime
- optional external correlation identifiers already present in canonical metadata

Purpose: enable deterministic attribution of OpenClaw events and artifacts back to canonical task history.

### 2) Objective, summary, and description

Projected as executor-readable problem statement input:

- canonical objective/intent
- summary and detailed task description
- bounded execution context needed to perform the assigned work

Purpose: communicate the assigned work without transferring policy authority.

### 3) Acceptance criteria

Projected as explicit executor targets:

- required outcomes
- required checks from task scope (as execution guidance only)
- completion expectations that help an executor understand “done candidate” behavior

Purpose: improve execution quality while keeping acceptance decisions in Harness.

### 4) Constraints

Projected as execution constraints:

- scope limitations
- forbidden actions
- runtime/environment limitations
- policy-relevant boundaries supplied as execution constraints

Purpose: constrain executor behavior without delegating policy adjudication.

### 5) Contextual references

Projected as optional supporting context:

- links/references needed to execute
- dependency references and upstream/downstream context pointers
- prior artifacts or history references explicitly included for execution

Purpose: provide enough context to execute without embedding alternative truth sources.

### 6) Artifact expectations

Projected as evidence-shaping hints:

- expected artifact classes (for example: PR, commit, files changed, logs)
- expected reference quality (stable identifiers rather than prose claims)
- expected provenance metadata fields to accompany produced artifacts

Purpose: improve downstream verification/reconciliation readiness.

### 7) Execution dependency/context references

Projected where required for runtime execution:

- environment/profile selectors
- execution prerequisites and dependency handles
- relevant adapter-safe execution metadata from dispatch context

Purpose: allow execution start while preserving control-plane semantics elsewhere.

## Harness-Only Fields and Semantics (Not Executor Truth)

The following remain Harness-owned and must never be treated as OpenClaw-owned truth:

- lifecycle state (`queued`, `assigned`, `executing`, `in_review`, `completed`, `blocked`, etc.)
- lifecycle transition policy and enforcement rules
- verification decisions and evidence sufficiency outcomes
- reconciliation outcomes against external systems
- manual review gate status, review decisions, and sticky review semantics
- accepted completion/failure authority
- canonical state history and append-only evaluation history

OpenClaw may emit facts that inform these areas, but it does not define or mutate them as authoritative outcomes.

## Mapping Rules

The mapping is category-based, explicit, and one-way: canonical Harness input -> executor request projection.

### A) Forward directly

Forward canonical content directly when no executor-specific reshaping is needed:

- task/attempt identity fields
- objective/summary/description text
- acceptance criteria text
- explicit constraints and contextual references

Direct forwarding preserves semantic fidelity and lowers translation ambiguity.

### B) Transform for executor ergonomics

Transformation is allowed only for transport/usability, not for policy reinterpretation. Examples:

- restructuring canonical categories into OpenClaw request sections
- converting lists/objects into executor-expected shape
- normalizing field names or nesting for OpenClaw API compatibility

Rules for allowed transformation:

- do not change canonical meaning
- do not infer new lifecycle/verification semantics
- keep reversible provenance where practical (so mapped outputs can be traced to canonical inputs)

### C) Omit when non-execution or policy-authoritative

Do not forward canonical fields that are not required for execution, especially Harness authority fields such as:

- lifecycle enforcement internals
- verification decisions
- reconciliation decisions
- manual review decisions
- acceptance/rejection authority markers

Omission here protects control-plane boundaries.

### D) Preserve provenance

For every mapped request, preserve enough provenance to audit the projection:

- mapping version identifier
- canonical task and attempt identifiers
- adapter identifier/version
- mapping timestamp
- references to source canonical categories used in projection

Provenance must be attachable to resulting execution events/artifact references.

### E) Never flatten into executor truth

The mapping must never flatten or reinterpret Harness control-plane semantics into executor-owned terminal states.

Disallowed examples:

- treating OpenClaw `success` as canonical `completed`
- treating OpenClaw `failed` as canonical terminal failure without Harness policy evaluation
- clearing/overriding active manual review based on executor events
- redefining reconciliation mismatch as resolved solely by executor claim

## Output and Provenance Expectations from OpenClaw-Shaped Execution

OpenClaw-side execution outputs must come back as normalized, advisory facts suitable for Harness evaluation and audit.

### 1) Execution events and traces

Expected categories:

- start/progress/block/failure/completion-claimed style events
- ordered timestamps
- OpenClaw run/execution identifiers
- trace/log references retrievable for diagnostics

Requirement: events must be attributable to canonical task + attempt identity.

### 2) Artifact references

Expected categories:

- PR/commit/branch references where produced
- file/log/report/output references
- stable external identifiers and retrieval locators

Requirement: references must include provenance sufficient for verification and reconciliation, not just human-readable summaries.

### 3) Executor metadata

Expected categories:

- executor name/type (OpenClaw)
- executor run id(s)
- adapter version/mapping version
- timing/attempt diagnostics

Requirement: metadata is advisory telemetry, not lifecycle authority.

### 4) Provenance fields required for Harness verification/reconciliation

At minimum, outputs must preserve:

- canonical `task_id`
- execution `attempt_id`
- source executor run identifier(s)
- timestamped event lineage
- artifact source attribution (where artifact came from and how it was observed)
- mapping/adapter version used to generate request

These fields are required so Harness can perform deterministic verification, external reconciliation, and auditable reevaluation.

## Explicit Non-Goals

This document does **not**:

- implement payload builders
- validate OpenClaw request schemas or transport wiring
- add runtime OpenClaw integration code
- expand `TaskEnvelope` semantics to fit executor ergonomics
- change lifecycle, verification, reconciliation, or manual-review semantics
- weaken the rule that executor claims are advisory only

## Implementation Guidance Boundary

Future implementation should treat this document as a projection specification and must still route completion claims through canonical Harness evaluation and reevaluation paths.

If an implementation pressure requires changing control-plane semantics to satisfy OpenClaw request shape, the implementation is out of bounds and this mapping must not be used to justify the change.
