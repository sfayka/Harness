# Harness Evolution Engine

## Purpose

Define the future advisory subsystem that learns from real Harness execution traces, evaluation outcomes, and manual review decisions to diagnose recurring failure modes and later propose improvements.

This document is planning-only. It does not authorize runtime mutation, autonomous code changes, or any change to current end-to-end automation behavior.

## Why It Exists

Harness already records append-only task state, evaluation history, timelines, artifacts, and review outcomes.

If those records remain structured and auditable, they can later support:

- diagnosis of recurring failure patterns
- operator-visible suggestions about weak contracts or missing evidence
- evidence-backed proposals for improving Harness policy, adapters, or execution handling

The goal is to turn observed outcomes into better future design inputs without changing the rule that Harness remains the control plane and source of lifecycle truth.

## Responsibilities

The future Harness Evolution Engine (HEE) should own only advisory work such as:

- collecting or referencing canonical execution traces and outcomes
- producing structured failure diagnoses from repeated task results
- producing structured evolution candidates or proposals for human review
- preserving provenance from traces, evaluations, artifacts, and review decisions
- exposing advisory outputs for inspection without mutating task truth

## Explicit Non-Responsibilities

HEE must not:

- change live task state or lifecycle semantics on its own
- bypass `TaskEnvelope`, reevaluation, or canonical enforcement paths
- act as an executor, planner, or ingress surface
- auto-generate pull requests or merge code changes
- auto-edit prompts, policies, schemas, or adapter behavior in production
- treat executor self-report as completion truth
- replace human review for high-risk control-plane changes

## Inputs

Future HEE inputs should come from canonical Harness records, not ad hoc side channels.

Expected inputs:

- `TaskEnvelope` snapshots and identifiers
- evaluation history records
- task timeline entries
- normalized execution trace facts and attempt outcomes
- artifact metadata and proof-of-completion evidence references
- reconciliation results and mismatch records
- manual review decisions and review notes

## Outputs

HEE outputs should be advisory artifacts that can be inspected and reviewed.

Expected outputs:

- structured failure diagnosis records
- structured evolution candidate records
- operator-facing summaries or recommendations
- references to the evidence used to justify the diagnosis or proposal

These outputs are not lifecycle decisions and do not authorize runtime behavior changes by themselves.

## Relationship To Existing Harness Concepts

### TaskEnvelope

`TaskEnvelope` remains the canonical task contract. HEE may analyze completed or in-flight records derived from it, but it does not redefine task meaning.

### Lifecycle States

Lifecycle state remains policy-enforced by Harness core. HEE may reference outcomes such as `blocked`, `completed`, `failed`, or `in_review`, but it does not assign them.

### Execution Traces

Execution traces are a future evidence source for HEE. They should describe what happened during task attempts without being treated as correctness proof on their own.

### Artifacts And Proof Of Completion

Artifacts, verification summaries, reconciliation summaries, and review decisions remain the basis for trusted completion. HEE may learn from those results, but it cannot replace them.

## Future Implementation Notes

- Keep HEE outputs append-only and auditable, similar to evaluation history.
- Separate diagnosis from proposal generation so observed failures and recommended changes do not collapse into one opaque step.
- Prefer explicit contracts for diagnoses and proposals before building any model or scoring logic.
- Start with operator-reviewed outputs before considering any workflow that could draft code or policy changes.
- Use canonical inspection surfaces and stored facts where possible rather than introducing a parallel truth store.

## Boundary Summary

HEE is a future advisory subsystem for diagnosis and proposal generation.

It is not a runtime mutation engine.
