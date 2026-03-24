# Harness

Harness is a control plane and reliability layer for AI-assisted work.

The goal is not to out-reason model-native task runners. The goal is to make AI-driven execution reliable, auditable, artifact-backed, and aligned with system-of-record workflows.

The Harness runtime is Python. Integration with OpenClaw is API-first rather than a Node extension model.

## Purpose

Harness is a continuation of the ideas behind InboxToBacklog, but in a fresh repository with a tighter focus on correctness, verification, and control-plane guarantees.

At a high level, Harness should:

- accept work through explicit contracts
- normalize work into canonical task structures
- delegate execution to replaceable workers
- require evidence before trusting completion
- maintain explicit blocked, failed, and completed semantics
- reconcile state across systems of record such as Linear and GitHub
- provide an auditable record of what was planned, executed, verified, and finished

## Problem Statement

Model-native task execution will continue to improve. That is not Harness's moat.

The missing layer is reliable task control:

Harness exists to fill that gap:

- make work contracts explicit
- make lifecycle state auditable
- enforce artifact-backed completion
- reconcile execution claims against external systems of record
- surface blocked and failed outcomes instead of assuming successful autonomy

## Rough Workflow

1. A user gives Openclaw a request.
2. Openclaw asks follow-up questions if needed.
3. Openclaw hands validated work to Harness.
4. Harness normalizes the request into canonical task structures.
5. Harness decomposes the work and delegates execution to replaceable workers.
6. Harness watches progress, blocked states, failures, and evidence collection.
7. Harness verifies completion against artifacts and system-of-record state.
8. Harness aggregates verified outcomes and reports status back upstream.

## Early Scope

This repository is expected to grow toward:

- canonical task contracts
- lifecycle enforcement and audit trails
- artifact tracking and completion verification
- system-of-record reconciliation across Linear and GitHub
- decomposition and assignment logic
- reporting back to the controlling interface

## Initial Constraints

For now, Harness should optimize for clarity over automation theater.

- every task should have explicit state
- delegation should be visible and reviewable
- completion should not be trusted without artifacts
- stalled or failed work should be surfaced instead of silently ignored
- upstream reporting should be grounded in verified task status
- ambiguous requests should be clarified before decomposition when possible

## Status

This is an early project scaffold. The README currently captures the intent and operating model so the repo has a concrete starting point.

## Architecture Docs

The architecture baseline for Epic 1 lives under `docs/`:

- [System Context](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/system-context.md)
- [TaskEnvelope Contract](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/task-envelope.md)
- [Artifact And Completion Evidence](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/artifact-and-completion-evidence.md)
- [Intake To TaskEnvelope Mapping](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/intake-to-task-envelope.md)
- [Module Boundaries](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/module-boundaries.md)
- [Canonical Vocabulary](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/canonical-vocabulary.md)
- [Repository Layout Proposal](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/repository-layout.md)
- [ADR 0001](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/adrs/0001-openclaw-as-ingress-harness-as-control-plane.md)
- [ADR 0002](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/adrs/0002-initial-substrate-choice-and-replacement-strategy.md)
- [ADR 0003](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/adrs/0003-harness-implementation-runtime.md)
- [ADR 0004](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/adrs/0004-harness-strategic-positioning-reliability-layer.md)
- [Initial Codex Tickets](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/planning/initial-codex-tickets.md)
