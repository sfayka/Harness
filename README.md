# Harness

Harness is a control plane and reliability layer for AI-assisted work.

It does not try to make AI smarter.

It makes AI-driven work **reliable, auditable, and actually complete**.

The goal is not to out-reason model-native task runners. The goal is to ensure that execution is artifact-backed, verifiable, and aligned with system-of-record workflows.

The Harness runtime is Python. Integration with OpenClaw is API-first rather than a Node extension model.

## Why Harness Exists

AI agents are getting better at reasoning and execution.

But that is not the real bottleneck.

The real problem is that there is no reliable system around them.

Today:
- tasks are loosely defined
- execution is opaque
- completion is based on what an agent says, not what actually happened
- there is no consistent way to verify, audit, or reconcile work

This leads to:
- tasks marked “done” with no artifacts
- work executed in the wrong repo or context
- silent failures or partial completion
- constant human babysitting

Harness exists to solve this problem.

Harness is a continuation of the ideas behind InboxToBacklog, extended into a full control-plane system focused on correctness, verification, and auditability.

---

## What Harness Is

Harness is a **control plane and reliability layer for AI-driven work**.

It enforces that:
- work is defined through explicit contracts (TaskEnvelope)
- execution is delegated to replaceable workers (Codex, Claude, etc.)
- completion is not accepted without verifiable artifacts (PRs, commits, etc.)
- task lifecycle state is explicit (blocked, failed, completed)
- system-of-record tools (e.g. Linear, GitHub) stay consistent with reality

Harness does not try to make AI “smarter.”

It makes AI-driven work **reliable, auditable, and actually complete**.

---

## What Harness Is Not

Harness is not:

- an agent framework
- a multi-agent coordination system
- a planner/router competing with model-native reasoning
- a replacement for Codex, Claude, or similar systems

Those systems are **workers**.

Harness is the system that ensures their work is correct.

---

## Core Principle

> Work is not complete because an agent says it is complete.  
> Work is only accepted as complete when it is backed by verifiable evidence.

This principle drives:
- artifact modeling
- completion rules
- reconciliation with external systems
- auditability of all outcomes

---

## Current Direction

The project is actively evolving toward:

- artifact-backed completion and verification
- reconciliation between Harness, GitHub, and Linear
- explicit clarification and missing-information handling
- explicit lifecycle semantics (including failure and blocked states)
- treating executors as replaceable components behind contracts

This is a **build-in-public** effort. Expect rough edges, but a clear direction.

## Rough Workflow

1. A user provides a request through an ingress layer (e.g. OpenClaw).
2. The request is clarified and normalized into a structured task.
3. Harness converts the request into canonical task contracts.
4. Work is decomposed and delegated to replaceable executors.
5. Harness tracks execution, blocked states, and failures.
6. Artifacts are collected and attached to tasks.
7. Completion is verified against artifacts and system-of-record state.
8. Verified outcomes are reported upstream.

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

Not production-ready. Architecture-first.

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

## License

Licensed under the Apache License 2.0.

## Architecture Docs

The architecture baseline for Epic 1 lives under `docs/`:

- [System Context](docs/architecture/system-context.md)
- [TaskEnvelope Contract](docs/architecture/task-envelope.md)
- [Artifact And Completion Evidence](docs/architecture/artifact-and-completion-evidence.md)
- [Reconciliation Rules](docs/architecture/reconciliation-rules.md)
- [Clarification And Missing Information](docs/architecture/clarification-and-missing-information.md)
- [Planner Contract](docs/architecture/planner-contract.md)
- [Dispatcher Contract](docs/architecture/dispatcher-contract.md)
- [Runtime Execution Contract](docs/architecture/runtime-execution-contract.md)
- [Verification And Completion Enforcement](docs/architecture/verification-and-completion-enforcement.md)
- [Intake To TaskEnvelope Mapping](docs/architecture/intake-to-task-envelope.md)
- [Module Boundaries](docs/architecture/module-boundaries.md)
- [Canonical Vocabulary](docs/architecture/canonical-vocabulary.md)
- [Repository Layout Proposal](docs/architecture/repository-layout.md)
- [ADR 0001](docs/adrs/0001-openclaw-as-ingress-harness-as-control-plane.md)
- [ADR 0002](docs/adrs/0002-initial-substrate-choice-and-replacement-strategy.md)
- [ADR 0003](docs/adrs/0003-harness-implementation-runtime.md)
- [ADR 0004](docs/adrs/0004-harness-strategic-positioning-reliability-layer.md)
- [Initial Codex Tickets](docs/planning/initial-codex-tickets.md)

## System Overview

![System Diagram](docs/architecture/system-context.png)

## Contributing

Lightweight contributor guidance lives in [CONTRIBUTING.md](CONTRIBUTING.md).
