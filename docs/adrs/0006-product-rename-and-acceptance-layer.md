# ADR 0006: Rename The Product Around Acceptance

## Status

Proposed

## Context

`Harness` has become an overloaded term in the frontier-model ecosystem. OpenAI has also used Harness language publicly, and Symphony now covers much of the executor-orchestration territory this repo originally explored.

That changes the naming problem and the product problem at the same time.

The product should not compete with Codex, Symphony, Hermes, or OpenClaw as an execution workbench. Those systems will keep adding scheduling, workspace, retry, and agent ergonomics. The durable product here is validation of agentic completion against user intent and evidence: the system that refuses to call work complete until intent, evidence, external facts, and review policy line up.

## Decision

Rename the product away from `Harness`.

Use `Proofline` as the recommended working product name.

The name fits the new positioning:

- it points at proof, not execution
- it implies a line work must cross before acceptance
- it does not sound like an agent runtime, IDE, scheduler, or PM tool
- it gives the product a distinct vocabulary while preserving the existing repository during migration

Until the rename is executed, `Harness` remains the repository and codebase name. Product docs should describe the system as agentic completion validation against user intent and evidence, and avoid expanding the old Harness brand.

## Product Boundary

Proofline is:

- validation of agentic completion against user intent and evidence
- a verifier of task contracts, GitHub artifacts, Linear state, CI/review facts, and manual-review decisions
- a reconciliation authority when intended work and artifact truth disagree
- a source of accepted lifecycle state
- a repair-request generator when work is incomplete or invalid

Proofline is not:

- an executor
- a Codex replacement
- a Symphony replacement
- a desktop-agent shell
- a PM tool
- a general planner
- a dashboard-first workflow manager

## Naming Migration Policy

Do not perform a broad mechanical rename in one PR.

Rename in layers:

1. Product language: README, architecture docs, AGENTS guidance, dashboard headings if applicable.
2. Public API language where it does not break clients.
3. Package and CLI names only after compatibility aliases exist.
4. Repository rename last, after CI, deployment, docs, and local scripts no longer assume the old name.

The current `TaskEnvelope` name should not be renamed casually. It is a contract name, not the product brand. Change it only if the schema versioning and downstream adapters can absorb the migration.

## Consequences

This explicitly reduces scope.

Keep investing in:

- task contract validation
- completion-claim handling
- GitHub proof validation
- Linear reconciliation
- manual review gates
- read-model and timeline inspection
- execution-substrate adapters that preserve advisory-only runner semantics

Stop investing in:

- custom executor scheduling
- native macOS product shell work
- broad planning intelligence
- direct runner ownership
- mutation-heavy dashboard workflows

## Follow-Up

The migration plan lives in [proofline-rename-migration.md](../architecture/proofline-rename-migration.md).

The first implementation PRs should update product copy, docs, and visible dashboard labels only. Code/package renames should wait until aliases, tests, deployment checks, and rollback steps exist.
