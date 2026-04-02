# ExecutorAdapter Contract

## Purpose

Define the canonical boundary between Harness control-plane logic and any execution engine adapter.

This contract is implementation-ready but implementation-neutral:

- it defines what every `ExecutorAdapter` must accept and return
- it defines what remains Harness authority
- it keeps executor behavior out of lifecycle semantics

## 1) Adapter Boundary

### Responsibilities

`ExecutorAdapter` is responsible for boundary translation and execution reporting only:

- accept canonical execution input derived from `TaskEnvelope`
- project canonical input into executor-specific request formats
- invoke the selected executor runtime
- normalize executor events and outputs into canonical execution results
- return artifact references and execution metadata with provenance

### Non-Responsibilities

`ExecutorAdapter` is **not** responsible for:

- defining or mutating canonical task lifecycle policy
- deciding task completion, failure, or manual-review outcomes
- overriding verification, reconciliation, or enforcement rules
- acting as source of truth for task state
- changing `TaskEnvelope` semantics
- introducing alternate submission or reevaluation paths

Harness control plane remains authoritative for lifecycle correctness, verification, reconciliation, and acceptance.

## 2) Inputs to ExecutorAdapter

Inputs must be canonical and executor-agnostic.

### Allowed input categories (from `TaskEnvelope` and dispatch context)

- stable task identity and execution-attempt identity
- objective, scope, and acceptance criteria
- constraints and policy-relevant execution limits
- artifact expectations (for example, expected PR/commit/file evidence classes)
- contextual references needed for execution (links, prior artifacts, dependency references)
- assignment metadata that identifies which executor implementation was selected

### Harness-only data (must not become adapter authority)

The adapter may receive read-only context, but must not treat these as mutable runtime-owned truth:

- canonical lifecycle state and transition policy
- verification decisions and enforcement outcomes
- reconciliation outcomes against external systems
- manual review gate state and review decisions
- final completion/failure authority

Adapter input projection must never redefine these semantics.

## 3) Outputs from ExecutorAdapter

Outputs are non-authoritative execution facts for Harness to evaluate.

### Required output categories

1. **Execution result events**
   - started / progress / blocked / failed / completion-claimed style events
   - normalized status payloads suitable for append-only history
2. **Artifact references**
   - references to PRs, commits, branches, files, logs, traces, or other produced evidence
   - stable identifiers and source provenance for later verification/reconciliation
3. **Execution metadata (advisory)**
   - runtime diagnostics (duration, retry count, executor run id, environment hints)
   - adapter-level mapping notes required for auditability

### Output constraints

- outputs must be timestamped and attributable to executor + attempt
- outputs must be safe for audit trails (append-only facts, no hidden mutation semantics)
- outputs must not declare terminal lifecycle truth

## 4) Completion Semantics

Executor completion claims are **advisory only**.

A completion claim from any adapter means only: "the executor reports work as done."

It does **not** mean Harness must mark the task `completed`.

Only Harness verification and reconciliation policy may determine:

- accepted completion
- rejected completion / insufficient evidence
- failure classification
- escalation to manual review (`requires_review=true` -> `in_review`)

Executor outputs inform evaluation; they do not decide it.

## 5) Replaceability Constraint

The contract is strictly executor-agnostic:

- OpenClaw is not special.
- Codex is not special.
- Claude is not special.
- Any other executor is not special.

Any executor must be swappable behind this contract without changing:

- `TaskEnvelope` canonical meaning
- lifecycle policy semantics
- verification/reconciliation authority
- manual-review behavior

If swapping executors requires control-plane semantic changes, the adapter contract has been violated.

## 6) Non-Goals

This document intentionally does **not** define:

- runtime implementation details
- API wiring or endpoint shapes
- transport protocols (HTTP, queue, RPC, etc.)
- vendor-specific payload schemas
- scheduling or orchestration strategy

Those decisions may vary by implementation, but must conform to this contract.

## Canonical In-Code Model Mapping

Harness now codifies this contract in `modules/contracts/execution_advisory.py` with four distinct model groups:

- `ExecutionEvent` + `ExecutionEventType` for append-only execution event history
- `ArtifactReference` for emitted artifact pointers that still require later validation
- `ExecutionProvenance` for source attribution on events and artifacts
- `AdvisoryCompletionClaim` for non-authoritative executor completion claims

Validation enforces non-empty provenance and explicitly rejects lifecycle-authority fields (`target_status`, `canonical_status`, `lifecycle_status`, `authorized_transition`) in advisory payload metadata so adapters cannot self-authorize canonical transitions.

## Compliance Checklist

An `ExecutorAdapter` implementation is contract-compliant only if all statements below hold:

- it translates canonical inputs without redefining control-plane semantics
- it emits normalized execution facts, artifact references, and advisory metadata
- it never self-authorizes completion/failure/review outcomes
- it preserves executor replaceability without policy drift in Harness
