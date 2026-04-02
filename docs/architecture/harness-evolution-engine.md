# Harness Evolution Engine (HEE)

## Status

Planning architecture only.

This document defines boundaries for a future advisory subsystem. It does not authorize new runtime capabilities in current Harness releases.

## Purpose

Harness Evolution Engine (HEE) is the future advisory layer that analyzes historical Harness outcomes to produce operator-reviewable diagnoses and evolution proposals.

HEE exists to help humans improve Harness over time while preserving existing control-plane invariants:

- task truth remains canonical in Harness lifecycle and read-model surfaces
- completion remains evidence-backed and policy-enforced
- external systems (Linear, GitHub, executors) remain fact sources, not truth authorities

## Scope

HEE scope is intentionally narrow:

1. ingest canonical historical records from Harness-owned stores
2. derive recurring failure/quality patterns from those records
3. emit structured, inspectable advisory outputs with provenance
4. route those outputs into explicit human review workflows

HEE does not change live task outcomes.

## Non-Goals

HEE explicitly does **not** include:

- model training, model selection, or autonomous learning loops
- automatic code edits, PR creation, merge, or deployment
- runtime mutation of task lifecycle or policy decisions
- replacement of evaluator, verifier, reconciler, or manual review controls

## Control-Plane Boundary

HEE sits **outside** canonical lifecycle enforcement.

- Harness core remains responsible for `TaskEnvelope` validation, evaluation, reconciliation, and lifecycle transitions.
- HEE can read canonical historical facts and publish advisory artifacts.
- HEE cannot write canonical task truth (`status`, lifecycle state, completion decision, reconciliation decision).

If HEE is unavailable, Harness task execution and enforcement must remain fully functional.

## Data Contract Boundaries

### Canonical Inputs (read-only)

HEE may consume only canonical records or explicit derived snapshots from:

- `TaskEnvelope` snapshots/identifiers
- evaluation history (append-only)
- task timeline entries
- verification, evidence, and reconciliation summaries
- artifact metadata and completion-proof references
- execution trace summaries
- manual review decisions and reviewer notes

### Required Input Semantics

- executor-reported success remains advisory
- mismatches, insufficiency, and review gates remain distinct classes
- manual-review gates remain sticky until explicit human resolution

HEE must preserve those distinctions in any diagnosis output.

## Advisory Output Model

HEE outputs are advisory records, not state transitions.

Minimum output shape expectations:

- stable advisory identifier
- advisory type (`diagnosis`, `proposal`)
- confidence/explanation metadata
- provenance list referencing source records
- impacted boundary area (`schema`, `policy`, `adapter`, `operator_runbook`, etc.)
- explicit recommendation for human review action

Outputs must be append-only and auditable.

## Review And Decision Flow

1. HEE publishes advisory record.
2. Operators/reviewers inspect provenance and rationale.
3. Humans decide whether to create a tracked change (issue/PR/policy update).
4. Any accepted change re-enters Harness through normal repo and deployment processes.

No advisory output is self-executing.

## Relationship To Core Harness Concepts

### `TaskEnvelope`

`TaskEnvelope` remains canonical task contract and submission surface. HEE may analyze envelopes historically but cannot redefine or bypass the contract.

### Evaluation History

Evaluation history remains append-only truth for policy outcomes. HEE may aggregate repeated patterns but cannot overwrite or collapse historical records.

### Timeline

Timeline remains canonical audit surface for task progression. HEE may reference timeline events as evidence but cannot retroactively alter event ordering or meaning.

### Execution Traces

Execution traces are descriptive evidence of what happened during attempts. HEE may use them for diagnosis but they never become authoritative completion proof by themselves.

Trace minimum-field expectations for future HEE inputs are defined in `modules/evolution/contracts/execution-trace-requirements.contract.md`.

### Artifacts And Completion Evidence

Artifacts and verification/reconciliation outcomes remain completion authority under policy. HEE can propose improvements to artifact requirements, but cannot grant completion.

### Manual Review Decisions

Manual review remains explicit human governance. HEE may suggest escalation patterns but cannot clear or resolve review gates.

## Failure-Containment Requirements

Any future HEE implementation must fail safe:

- no write path from HEE into lifecycle transition handlers
- no implicit coupling that blocks canonical submission (`POST /tasks`) or reevaluation (`POST /tasks/<task_id>/reevaluate`)
- advisory generation failures must degrade to “no advice available,” not policy bypass

## Boundary Summary

Harness Evolution Engine is a planning-stage, advisory-only architecture for diagnosis and proposal generation.

Harness lifecycle truth, policy enforcement, and completion authority remain outside HEE.
