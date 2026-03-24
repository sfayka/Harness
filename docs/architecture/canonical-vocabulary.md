# Canonical Vocabulary

## Purpose

Define the words Harness will use consistently so documentation and implementation do not drift.

## Terms

### Ingress

The user-facing entry point that receives requests, asks clarifying questions, and hands validated work into Harness.

For this architecture, OpenClaw is the ingress.

### Harness

The control plane and reliability layer responsible for normalizing work, delegating execution, verifying completion, and enforcing lifecycle correctness.

### Control Plane

The part of the system that decides what work exists, who owns it, what state it is in, and what should happen next.

### Structured Work

The durable project, epic, task, and dependency records that represent planned or active work.

Linear is the source of truth for structured work.

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
- GitHub is the source of truth for code artifacts.
- the workflow substrate is the source of truth for resumable orchestration state
- executors are the source of truth only for their immediate runtime outputs until Harness applies policy

### System-Of-Record Alignment

The discipline of keeping Harness lifecycle decisions consistent with the authoritative state held in systems such as Linear and GitHub.

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
- Use `verification` or `evidence` instead of vague claims like `done` when artifact checks are required.
