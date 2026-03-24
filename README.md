# Harness

Harness is a control plane and reliability layer for AI-assisted work.

The goal is not to out-reason model-native task runners. The goal is to make AI-driven execution reliable, auditable, artifact-backed, and aligned with system-of-record workflows.

The Harness runtime is Python. Integration with OpenClaw is API-first rather than a Node extension model.

## What Harness Is

Harness is a system for:

- receiving validated work through explicit contracts
- normalizing work into canonical task structures
- delegating execution to replaceable workers
- requiring evidence before trusting completion
- reconciling lifecycle state across systems such as Linear and GitHub

## What Harness Is Not

Harness is not:

- a generic agent framework
- a model-hosted plugin extension
- a bet against improving model-native reasoning
- a system that treats executor-reported success as sufficient evidence of completion

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

This repository is still early, but the architecture direction is established.

Current focus:

- canonical contracts such as `TaskEnvelope`
- artifact and completion evidence modeling
- intake normalization
- verification, auditability, and system-of-record reconciliation

Not yet in scope:

- full planner sophistication
- advanced dispatcher behavior
- workflow-heavy runtime features beyond what is needed for control-plane guarantees

## Explore The Repo

- `docs/architecture/` contains the main system model and contract docs
- `docs/adrs/` contains architecture decision records
- `docs/planning/` contains near-term planning notes
- `modules/` contains the current Python implementation work
- `schemas/` contains canonical machine-readable contracts
- `tests/` contains Python tests for contract validation and module behavior

## Public Readiness Notes

- No license file has been added in this change set because license selection should be maintainer-confirmed before the repository is made public.
- Secrets and local-only files should continue to be reviewed before changing repository visibility, even though this pass did not find obvious committed credentials.

## Architecture Docs

The architecture baseline for Epic 1 lives under `docs/`:

- [System Context](docs/architecture/system-context.md)
- [TaskEnvelope Contract](docs/architecture/task-envelope.md)
- [Artifact And Completion Evidence](docs/architecture/artifact-and-completion-evidence.md)
- [Intake To TaskEnvelope Mapping](docs/architecture/intake-to-task-envelope.md)
- [Module Boundaries](docs/architecture/module-boundaries.md)
- [Canonical Vocabulary](docs/architecture/canonical-vocabulary.md)
- [Repository Layout Proposal](docs/architecture/repository-layout.md)
- [ADR 0001](docs/adrs/0001-openclaw-as-ingress-harness-as-control-plane.md)
- [ADR 0002](docs/adrs/0002-initial-substrate-choice-and-replacement-strategy.md)
- [ADR 0003](docs/adrs/0003-harness-implementation-runtime.md)
- [ADR 0004](docs/adrs/0004-harness-strategic-positioning-reliability-layer.md)
- [Initial Codex Tickets](docs/planning/initial-codex-tickets.md)

## Contributing

Lightweight contributor guidance lives in [CONTRIBUTING.md](CONTRIBUTING.md).
