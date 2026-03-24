# System Context

## Objective

Define the top-level system model before implementation so future modules do not blur ingress, orchestration, work tracking, and execution.

## System Framing

Harness sits between the user-facing agent layer and the execution layer.

- OpenClaw is the ingress layer.
- Harness is the control plane.
- Linear is the source of truth for structured work.
- Executors such as Codex are workers.
- The workflow substrate provides persistence, resumability, and coordination state for Harness itself.

## Context Diagram

The Mermaid source for the diagram lives in [system-context.mmd](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/system-context.mmd).

```mermaid
flowchart LR
    U["User"] --> O["OpenClaw\nIngress and clarification"]
    O --> H["Harness\nControl plane"]
    H --> L["Linear\nStructured work source of truth"]
    H --> S["Workflow substrate\nPersistence and resumability"]
    H --> E["Executors\nCodex and future workers"]
    E --> H
    H --> O
```

## Responsibilities By System

### OpenClaw

- collects user intent
- asks follow-up questions when intent is ambiguous
- hands validated work into Harness
- presents progress and results back to the user

### Harness

- translates validated requests into structured work
- decomposes work into manageable tasks
- decides assignment and reassignment
- monitors progress and exceptions
- aggregates outcomes for upstream reporting

### Linear

- stores epics, projects, tasks, and task state
- provides the durable structured record of planned and active work
- serves as the reference point for task ownership and status

### Workflow Substrate

- persists orchestration state that should survive crashes or restarts
- allows resumable long-running workflows
- stores execution checkpoints and internal coordination state
- does not replace Linear as the source of truth for work items

### Executors

- perform assigned work
- report execution progress and outputs back to Harness
- remain replaceable behind stable task contracts

## Boundary Rules

- OpenClaw does not become the durable orchestrator.
- Harness does not become the user interface.
- Linear owns structured work records, not executor internals.
- Executors do not own planning, routing, or lifecycle policy.
- The workflow substrate owns resumability, not product-level work semantics.

## Architectural Implications

- ingress, orchestration, source-of-truth, and execution remain separable
- executor implementations can change without changing Harness core planning logic
- workflow technology can change if Harness state transitions are modeled explicitly
