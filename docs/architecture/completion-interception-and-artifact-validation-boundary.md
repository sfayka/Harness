# Completion Interception And Artifact Validation Boundary

## Purpose

Define the control-plane boundary for executor-reported completion.

This contract ensures that future executor adapters, including OpenClaw-shaped compatibility adapters, cannot directly mark tasks complete, bypass canonical reevaluation, or relocate artifact-validation responsibility outside Proofline.

## Problem This Boundary Solves

Executor runtimes can report "done" based on local process signals (exit codes, tool completion, emitted outputs). Those signals are useful execution facts, but they are not proof that policy-required completion conditions are satisfied.

Without an explicit boundary:

- executor status could be mistaken for lifecycle truth
- artifact references could be treated as validated evidence
- verification/reconciliation/manual-review gates could be unintentionally bypassed

Proofline must intercept completion claims and re-evaluate canonical task truth before any terminal lifecycle outcome is accepted.

The same boundary applies to integration proof. API receipts, webhook traces, retry logs, async job states, sandbox replay results, and external state snapshots are evidence inputs. They do not become lifecycle truth until Proofline validates them against task policy.

## Core Boundary Rule

**Completion claims from an executor are advisory execution facts, not authoritative lifecycle decisions.**

Proofline remains the sole authority for:

- lifecycle transitions
- policy enforcement
- evidence sufficiency decisions
- reconciliation decisions
- manual review gate enforcement

## Responsibility Split

### Executor Adapter Responsibilities

The adapter may:

- report execution state changes (started, progressed, failed, claimed-complete)
- attach normalized artifact references (URIs, IDs, provenance pointers)
- attach execution traces/log pointers
- attach integration-proof references such as API receipts, webhook correlation IDs, retry traces, or async job states
- preserve provenance about how outputs were produced

The adapter must not:

- mark the task as canonically `completed`
- clear a required review gate
- decide evidence sufficiency
- resolve reconciliation mismatches
- bypass canonical submission/reevaluation APIs

### Proofline Responsibilities

Proofline must:

- intercept every executor completion claim
- persist claim + references as advisory facts
- run canonical reevaluation (`POST /tasks/<task_id>/reevaluate` semantics)
- enforce verification, reconciliation, lifecycle, and manual-review policies
- keep evaluation history append-only and auditable
- publish resulting canonical truth through read-model/timeline surfaces

## Artifact Boundary

Artifacts split across two phases:

1. **Attachment phase (adapter-side):**
   - Adapter submits references to produced artifacts and related provenance.
   - These references are untrusted inputs.

2. **Validation phase (Proofline-side):**
   - Proofline evaluates artifact relevance/completeness under canonical policy.
   - Proofline combines artifact facts with verification/reconciliation/manual review state.
   - Only then can lifecycle advance to canonical completion.

Therefore:

- adapter **attaches** artifact references
- Proofline **validates** artifact sufficiency and completion eligibility

## Completion Interception Flow

1. Task is in an execution-capable lifecycle state (for example `assigned`/`executing`).
2. Executor adapter emits a completion claim with artifact + trace references.
3. Proofline records the claim as advisory execution input.
4. Proofline triggers canonical reevaluation.
5. Reevaluation computes verification/reconciliation/evidence/manual-review outcomes.
6. Proofline enforces lifecycle transition rules from reevaluation output.
7. Read-model and timeline expose the canonical result and audit trail.

At no point does adapter-reported "success" directly become canonical `completed` state.

## Policy Invariants Preserved

This boundary preserves existing Proofline invariants:

- agent/executor success is advisory only
- completion remains evidence-backed when policy requires evidence
- reconciliation mismatches are not silently ignored
- manual review is explicit and auditable
- `requires_review=true` moves canonical state to `in_review`
- active review gates remain sticky until explicit review resolution

## API Surface Expectations

Executor-facing integrations should continue to rely on canonical Harness compatibility paths:

- submission: `POST /tasks`
- reevaluation trigger: `POST /tasks/<task_id>/reevaluate`
- inspection: `GET /tasks`, `GET /tasks/<task_id>/read-model`, `GET /tasks/<task_id>/timeline`

No adapter-private shortcut may bypass canonical validation, persistence, or evaluation-history behavior.

## Relationship To Existing Planning Docs

This boundary document complements:

- `openclaw-executor-adapter.md` (future executor adapter scope)
- `task-envelope-to-openclaw-mapping.md` (canonical envelope mapping boundary)
- `codex-cloud-execution.md` (execution artifact and completion-proof requirements)

Together, these documents keep execution plumbing replaceable while preserving Proofline as the control-plane authority.
