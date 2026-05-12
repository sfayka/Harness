# Canonical Vocabulary

## Purpose

Define the words Harness will use consistently so documentation and implementation do not drift.

## Terms

### Ingress

The user-facing entry point that receives requests, asks clarifying questions, and hands validated work into Harness.

For this architecture, a desktop agent client such as OpenClaw, Hermes, or a future equivalent may act as ingress. Harness should stay tied to the role, not to one client implementation.

### Harness

The current repository and codebase name for the validation boundary.

`Harness` should no longer be treated as the long-term product name. Use it when referring to current code, APIs, historical docs, or repository paths. Product positioning should move toward the Proofline name and the agentic completion validation definition in ADR 0006.

### Proofline

The recommended working product name for validation of agentic completion against user intent and evidence.

Proofline is responsible for deciding whether an agent's claimed completion matches the user's intent, the task contract, current evidence, and reconciliation facts. It wraps execution tools, but it is not an executor.

The staged rename rules live in [proofline-rename-migration.md](proofline-rename-migration.md).

### Control Plane

The part of the system that decides what work exists, who owns it, what state it is in, and what should happen next.

Use carefully. The durable product direction is narrower than a broad control plane: acceptance, verification, reconciliation, and lifecycle enforcement.

### Structured Work

The durable project, epic, task, and dependency records that represent planned or active work.

Linear is the source of truth for structured work and the primary human-and-agent work surface.

### Work Surface

The place where humans and agents coordinate around tasks, issues, projects, and workflow state.

In this architecture, Linear is the work surface.

### Artifact Evidence

The external evidence used to support completion claims, such as pull requests, commits, logs, or generated outputs.

GitHub is the primary source of truth for code-bearing artifact evidence.

### Workflow Substrate

The persistence and resumability layer used by Harness to survive restarts, resume long-running orchestration, and track internal execution progress.

### Executor

A worker capable of performing assigned tasks according to a stable contract.

Codex is an initial executor, not the only possible executor. Executors are replaceable workers, not the control plane.

### Task

The smallest unit of structured work that Harness intends to assign and monitor as a single owned outcome.

### Assignment

The decision that a specific executor type or executor instance owns a task.

### Execution Event

A progress, result, failure, or heartbeat message emitted by an executor and consumed by Harness.

### Trace Segment

One contiguous execution-context span inside an attempt. A new segment usually starts after replay, retry, resume, compaction, handoff, or manual-review follow-up.

### Trace Continuity

The lineage model that preserves how trace segments, context snapshots, compacted summaries, handoff artifacts, attempts, and review decisions relate over time.

Trace continuity is inspection truth, not completion truth.

### Long-Session Risk

The runtime and continuity risk that a long-running agent session may no longer be trustworthy without a checkpoint, handoff, fresh validation, or manual review.

Long-session risk can require additional evidence before continuation or acceptance. It is not completion truth and its absence does not prove that work is done.

### Execution Budget

The policy and ledger model that records authorized and consumed spend, runtime, retry count, fan-out, and tool-use limits for delegated execution.

Budget governance controls continuation. It does not decide completion.

### Local Eval Harness

A local-first regression harness for skills and delegated workflows. It compares reproducible fixture runs against baselines and links results back to canonical Harness surfaces when present.

### Verification

The process of deciding whether a task outcome is trustworthy enough to move into a terminal lifecycle state.

Verification may include artifact checks, system-of-record reconciliation, and policy enforcement.

### Artifact-Backed Completion

The rule that completion is not accepted purely because a worker claims success. Completion must be supported by task-appropriate evidence when evidence is expected.

### Reliability Layer

The part of the system that enforces correctness, auditability, verification rules, and explicit lifecycle semantics across AI-assisted work.

### Decomposition

The transformation of a validated request into smaller, structured tasks with explicit dependencies and ownership boundaries.

### Source Of Truth

The system whose records are authoritative for a particular class of information.

In this architecture:

- Linear is the source of truth for structured work.
- Linear is the work surface for structured work coordination.
- GitHub is the source of truth for code artifacts.
- the workflow substrate is the source of truth for resumable orchestration state
- executors are the source of truth only for their immediate runtime outputs until Harness applies policy

### System-Of-Record Alignment

The discipline of keeping Harness lifecycle decisions consistent with the authoritative state held in systems such as Linear and GitHub.

### Completion Enforcement

The policy-driven decision about whether a claimed completed state should be accepted, blocked, reversed, or escalated to review.

Harness owns completion enforcement. Linear may display the result, but it does not replace that policy function.

### Completion Validation Summary

The canonical read-model projection that condenses intent, evidence, reconciliation, review, and verification state into one operator-readable answer about whether claimed completion has been accepted.

This is a projection, not a mutation surface. It should make Proofline's core promise inspectable without letting the dashboard or a client invent its own completion truth.

### Acceptance Layer

Legacy shorthand for Proofline's role above execution tools. Prefer the more precise phrase: validation of agentic completion against user intent and evidence.

The acceptance layer can request repair or retry work. It does not perform the worker execution itself.

## Terms To Avoid Or Use Carefully

### Agent

Use only when the distinction does not matter. Prefer `ingress`, `harness`, or `executor` when the specific role matters.

### Workflow

Use for orchestration progress or substrate-managed execution flow, not as a synonym for project or task.

### Job

Avoid as a top-level product term until a specific definition is adopted. Prefer `task` or `execution` depending on meaning.

### Memory

Avoid as a system-wide architecture term. Use `structured work state`, `workflow state`, or `execution output` instead.

## Naming Rules

- Prefer role-based terms over implementation names.
- Name modules by responsibility, not by vendor.
- Separate business state from runtime state in naming.
- Use `executor` as the abstraction and `Codex` as one implementation.
- Use `agentic completion validation`, `user intent`, `evidence`, and `reconciliation` for product language instead of broad executor-orchestration language.
- Use `verification` or `evidence` instead of vague claims like `done` when artifact checks are required.
- Use `Linear` when referring to the work surface or structured-work system of record, not as a synonym for the Harness control plane.
