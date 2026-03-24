# System Context

## Objective

Define the top-level system model before implementation so future modules do not blur ingress, control-plane enforcement, systems of record, and execution.

## System Framing

Harness sits underneath the user-facing and agent-facing work surface as the system that enforces correctness.

- OpenClaw is the ingress layer.
- Linear is the human-and-agent work surface and the source of truth for structured work.
- Harness is the control plane and reliability layer beneath that work surface.
- GitHub is the source of truth for code artifacts such as pull requests and commits.
- Executors such as Codex are workers.
- The workflow substrate provides persistence, resumability, and coordination state for Harness itself.

Stated another way:

- Linear is the source of truth for intended work.
- GitHub is the source of truth for executed artifacts.
- Harness is the source of truth for verified state and lifecycle correctness.

## Context Diagram

The Mermaid source for the diagram lives in [system-context.mmd](system-context.mmd).

```mermaid
flowchart LR
    U["User"] --> O["OpenClaw\nIngress and clarification"]
    O --> L["Linear\nWork surface and structured work source of truth"]
    L --> H["Harness\nControl plane and reliability layer"]
    H --> G["GitHub\nArtifact evidence source of truth"]
    H --> S["Workflow substrate\nPersistence and resumability"]
    H --> E["Executors\nCodex and future workers"]
    E --> H
    H --> L
    L --> O
```

## Responsibilities By System

### OpenClaw

- collects user intent
- asks follow-up questions when intent is ambiguous
- hands validated work into Harness
- presents progress and results back to the user

### Harness

- consumes validated or synchronized work from ingress and work-surface systems
- translates that work into canonical control-plane contracts
- decomposes work into manageable tasks when needed
- delegates execution to replaceable workers
- enforces explicit lifecycle semantics, including blocked and failed states
- verifies completion against artifacts and system-of-record state
- aggregates verified outcomes for upstream reporting and work-surface reconciliation

### Linear

- stores epics, projects, issues, tasks, and workflow state
- provides the durable structured record of planned and active work
- acts as the primary human-and-agent work coordination surface
- serves as the reference point for task visibility, ownership, and workflow status
- does not decide whether artifact-backed completion should be trusted

### GitHub

- stores pull requests, commits, and code-review artifacts
- provides evidence used for completion verification in code-bearing workflows
- serves as an external artifact system, not as the control plane

### Workflow Substrate

- persists orchestration state that should survive crashes or restarts
- allows resumable long-running workflows
- stores execution checkpoints and internal coordination state
- does not replace Linear as the source of truth for work items

### Executors

- perform assigned work
- report execution progress and outputs back to Harness
- remain replaceable behind stable task contracts
- are not trusted as the source of truth for completion on their own

## Boundary Rules

- OpenClaw does not become the durable orchestrator.
- Harness does not become the user interface.
- Linear owns work coordination and structured work records, not completion enforcement semantics.
- GitHub owns artifact evidence records, not lifecycle policy.
- Executors do not own planning, routing, or lifecycle policy.
- The workflow substrate owns resumability, not product-level work semantics.
- completion is not accepted as true unless Harness can reconcile it with artifacts and system-of-record state

## Architectural Implications

- ingress, control-plane enforcement, systems of record, and execution remain separable
- Linear-facing coordination can evolve without changing Harness verification and enforcement logic
- executor implementations can change without changing Harness core planning logic
- workflow technology can change if Harness state transitions are modeled explicitly
- model-native reasoning improvements do not displace Harness as long as correctness, evidence, and auditability remain Harness-owned concerns
