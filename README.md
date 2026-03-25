# Harness

Harness is a control plane and reliability layer for AI-assisted work.

It is designed to sit underneath work surfaces such as Linear, not replace them.

It does not try to make AI smarter.

It makes AI-driven work **reliable, auditable, and actually complete**.

The goal is not to out-reason model-native task runners. The goal is to ensure that execution is artifact-backed, verifiable, and aligned with system-of-record workflows.

The Harness runtime is Python. Integration with OpenClaw is API-first rather than a Node extension model.

## Linear And Harness

Linear and Harness serve different roles.

- Linear is the work surface and system of record where humans and agents coordinate issues, projects, and workflow state.
- Harness is the control plane underneath that surface. It decides whether work is verified, reconciled, and acceptable as complete.

System-of-record model:

- Linear is the source of truth for intended work
- GitHub is the source of truth for executed artifacts
- Harness is the source of truth for verified state and lifecycle correctness

Harness is not trying to replace Linear's coordination layer.

Harness exists to answer questions a work surface alone should not answer by trust:

- did the work actually happen?
- is completion backed by evidence?
- do GitHub, Linear, and Harness agree?
- should completion be accepted, blocked, reversed, or sent to manual review?

At the contract boundary:

- Linear sends `issue_id`, `title`, `description`, optional labels and priority, and optional linked artifacts
- Harness derives the canonical `TaskEnvelope`, required artifacts, and verification expectations
- Harness returns a control-plane outcome plus evidence validation, reconciliation results, and required follow-up actions

Example feature flow:

1. A Linear issue is created.
2. Codex executes the work.
3. A GitHub pull request is opened.
4. Linear is marked done.
5. Harness verifies the PR, checks repo and branch correctness, and validates artifact completeness.
6. Harness returns `accepted_completion`, `blocked`, or `external_mismatch`.

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
- system-of-record tools such as Linear and GitHub stay consistent with reality

In practice:

- Linear remains the place where upstream work coordination happens
- Harness remains the place where correctness, verification, and enforcement happen

Harness does not try to make AI “smarter.”

It makes AI-driven work **reliable, auditable, and actually complete**.

---

## What Harness Is Not

Harness is not:

- an agent framework
- a multi-agent coordination system
- a replacement for Linear's work coordination surface
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
- a clean boundary where Linear remains the human-and-agent work surface
- explicit clarification and missing-information handling
- explicit lifecycle semantics (including failure and blocked states)
- treating executors as replaceable components behind contracts

This is a **build-in-public** effort. Expect rough edges, but a clear direction.

## Rough Workflow

1. A user provides a request through an ingress layer (e.g. OpenClaw).
2. The request is captured and coordinated in a work surface such as Linear.
3. Harness normalizes the relevant work into canonical task contracts.
4. Work is decomposed and delegated to replaceable executors.
5. Harness tracks execution, blocked states, and failures beneath the work surface.
6. Artifacts are collected and attached to tasks.
7. Completion is verified against artifacts plus system-of-record state in Linear and GitHub.
8. Verified outcomes are written back upstream so the work surface reflects reality.

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
- Linear-aligned intake and normalization
- verification, auditability, and system-of-record reconciliation

Not yet in scope:

- competing with Linear on issue/project coordination UX
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

## Local Demo

You can run the current control-plane evaluation loop locally through the minimal CLI/demo runner:

```bash
python -m modules.cli list
python -m modules.cli run accepted_completion
python -m modules.cli run blocked_reconciliation_mismatch --json
```

The CLI uses canonical `TaskEnvelope` fixtures plus normalized GitHub/Linear fact bundles.
It does not call live external APIs.

## Local HTTP API

You can also run a minimal local HTTP wrapper around the same evaluation entry point:

```bash
python -m modules.api --host 127.0.0.1 --port 8000 --store-root .harness-store
```

Then submit canonical evaluation requests to:

- `GET /health`
- `POST /evaluate`
- `POST /tasks/<task_id>/reevaluate`
- `GET /tasks/<task_id>`
- `GET /tasks/<task_id>/evaluations`

The API accepts canonical `TaskEnvelope` input plus normalized external facts and returns structured evaluation results.
Successful evaluations persist the current task snapshot and append an evaluation record under the configured store root.
Re-evaluation requests load the latest stored task, append any new canonical artifacts, apply new normalized facts or review outcomes, and persist the next task snapshot plus a new evaluation record.
It is a thin wrapper over the existing evaluator and store scaffolding, not a production service.

## License

Licensed under the Apache License 2.0.

## Architecture Docs

The architecture baseline for Epic 1 lives under `docs/`:

- [System Context](docs/architecture/system-context.md)
- [Linear And Harness Boundary](docs/architecture/linear-harness-boundary.md)
- [TaskEnvelope Contract](docs/architecture/task-envelope.md)
- [Artifact And Completion Evidence](docs/architecture/artifact-and-completion-evidence.md)
- [Reconciliation Rules](docs/architecture/reconciliation-rules.md)
- [Clarification And Missing Information](docs/architecture/clarification-and-missing-information.md)
- [Planner Contract](docs/architecture/planner-contract.md)
- [Dispatcher Contract](docs/architecture/dispatcher-contract.md)
- [Runtime Execution Contract](docs/architecture/runtime-execution-contract.md)
- [Verification And Completion Enforcement](docs/architecture/verification-and-completion-enforcement.md)
- [State Transition Enforcement](docs/architecture/state-transition-enforcement.md)
- [Operator And Manual Review](docs/architecture/operator-and-manual-review.md)
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
