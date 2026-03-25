# AGENTS.md

This file is for coding agents and automated contributors working in this repository.

## Repository Purpose

Harness is a control plane and reliability layer for AI-assisted work. It evaluates whether structured work is actually complete, evidence-backed, reconciled with external systems, and safe to accept.

Work surfaces and ingress clients sit above Harness. Harness owns verification, reconciliation, lifecycle enforcement, persistence of task truth, and inspection surfaces.

## Ownership Model

- agents execute work
- Linear tracks intended work
- GitHub proves execution artifacts
- Harness owns truth and lifecycle correctness

Keep that split intact.

## Architectural Boundaries

Do not collapse these roles:

- ingress clients submit canonical work or updates
- Harness normalizes and evaluates
- GitHub and Linear provide external facts
- dashboard reads canonical inspection APIs

Harness is not:

- a PM tool
- an agent runtime
- a chatbot UI
- a replacement for Linear coordination
- a place where worker claims are accepted without policy enforcement

## Non-Goals

Do not casually turn this repo into:

- a planner-intelligence product
- a generic project-management surface
- a mutation-heavy dashboard app
- a tightly coupled OpenClaw runtime extension
- a fake demo system that hides whether data is live or sample

## Invariants That Must Not Be Broken

1. Agent-reported success is advisory only.
2. Completion must remain evidence-backed when policy requires it.
3. Reconciliation mismatches must not be silently ignored.
4. Canonical lifecycle transitions remain policy-enforced.
5. `TaskEnvelope` remains the canonical task contract.
6. Read-model and timeline endpoints remain the canonical inspection surfaces.
7. Dashboard fallback/sample data must be clearly labeled and must never impersonate live backend truth.
8. Public API clients must go through canonical submission and reevaluation paths rather than internal shortcuts.
9. Evaluation history remains append-only and auditable.
10. Manual review remains explicit and auditable, not an informal bypass.

## Rules For Modifying TaskEnvelope And Schema

When changing `TaskEnvelope` or `schemas/task_envelope.schema.json`:

- preserve current canonical meaning unless a task explicitly changes the contract
- do not add fields casually to solve one adapter or UI need
- update both schema and architecture docs together
- update validation primitives and tests in the same change
- keep support artifacts, evidence, lifecycle, and extensions conceptually separate

Before claiming completion on contract changes:

- run schema validation if relevant
- run affected backend tests
- update docs under `docs/architecture/`

## Rules For Modifying Evaluator And Enforcement

Files under `modules/contracts/`, `modules/evaluation.py`, `modules/api.py`, and related store/read-model code are control-plane logic.

When changing them:

- preserve the distinction between invalid, insufficient, mismatched, blocked, deferred, review-required, and accepted outcomes
- do not let worker events authorize arbitrary lifecycle transitions
- do not bypass verification or reconciliation because a demo path wants a simpler result
- keep evaluation and persistence boundaries explicit

If a frontend or integration task pressures you to change backend semantics, verify the backend contract first. Prefer fixing projection or adapter logic before changing control-plane behavior.

## Rules For Modifying Read-Model And Timeline

The dashboard depends on:

- `GET /tasks`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`

Rules:

- preserve canonical read-model and timeline contracts
- do not rebuild core task truth in the frontend if the backend already exposes canonical summaries
- when canonical `verification_summary`, `reconciliation_summary`, or `evidence_summary` fields are present, use them directly
- keep timeline ordering correct and auditable
- do not turn read-model endpoints into mutation surfaces

## Rules For Modifying The Dashboard

The dashboard is currently read-only.

When changing frontend code:

- preserve the current product scope unless the task explicitly expands it
- use the canonical API surfaces, not private backend internals
- keep sample/fallback data explicit
- do not silently switch to mock data when the real backend fails
- avoid inventing ad hoc state derivations that contradict the canonical read-model

## Rules For Modifying Demo And Bootstrap Paths

Demo code exists for reproducibility and operator clarity.

When changing:

- `modules/demo_bootstrap.py`
- `modules/demo_walkthrough.py`
- `modules/demo_runner.py`
- `modules/simulator.py`

follow these rules:

- use public API paths rather than internal shortcuts
- keep seeded scenarios deterministic
- keep task IDs and walkthrough outputs stable when possible
- do not let demo helpers bypass persistence or evaluation behavior
- keep sample/fallback data clearly marked

## Rules For Modifying Integration Adapters

Current adapters and spikes are intentionally thin.

When changing Linear, OpenClaw, or ingress-side helpers:

- keep raw vendor payloads out of policy code
- translate into canonical TaskEnvelope and normalized fact models
- preserve ingress metadata without coupling Harness to client internals
- prefer thin builders/adapters over API redesign

The OpenClaw integration spike showed the API boundary is clean. Remaining ingress friction is request construction ergonomics, not architecture failure.

## Preserve Canonical Submission Paths

For new tasks:

- use `POST /tasks`

For reevaluation:

- use `POST /tasks/<task_id>/reevaluate`

Do not create shadow submission paths that bypass canonical validation, persistence, or evaluation history.

Thin wrappers such as `POST /ingress/linear` are acceptable only when they delegate back into canonical submission behavior.

## Preserve Canonical Read-Model And Timeline Contracts

For inspection:

- use `GET /tasks`
- use `GET /tasks/<task_id>/read-model`
- use `GET /tasks/<task_id>/timeline`

Do not add separate frontend-only truth sources for evidence, verification, reconciliation, or lifecycle summaries.

## Required Validation Before Claiming Work Complete

At minimum, run the validation that matches your change:

- docs-only: verify file paths, commands, and references
- backend Python changes: `.venv/bin/python -m unittest discover -s tests`
- frontend changes: `pnpm lint` and `pnpm build`
- mixed changes: run both backend and frontend validation as relevant

If you could not run a relevant check, say so explicitly.

## Documentation Expectations

When changing contracts, boundaries, API semantics, or run flows:

- update `README.md` if humans/operators need to understand the change
- update `AGENTS.md` if the repo-safe rules for future contributors change
- update the relevant architecture doc under `docs/architecture/`
- update setup/demo/integration docs when local or preview behavior changes

Do not leave the top-level README describing an older system than the code actually implements.

## Guidance On Live Vs Sample Data

This repository supports real local evaluation and dashboard inspection, but also uses labeled sample data for preview/fallback cases.

Rules:

- sample data must be clearly labeled
- preview fallback behavior must be honest
- do not silently pretend preview data is live backend truth
- do not remove fallback labels for cosmetic reasons

## Useful Starting Points

- [README.md](README.md)
- [docs/setup/local-development.md](docs/setup/local-development.md)
- [docs/architecture/system-context.md](docs/architecture/system-context.md)
- [docs/architecture/task-envelope.md](docs/architecture/task-envelope.md)
- [docs/architecture/module-boundaries.md](docs/architecture/module-boundaries.md)
- [docs/integration/openclaw-harness-spike.md](docs/integration/openclaw-harness-spike.md)
