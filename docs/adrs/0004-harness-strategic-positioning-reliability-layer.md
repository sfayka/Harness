# Harness Strategic Positioning: Reliability Layer For AI-Driven Work

- title: Harness strategic positioning: reliability layer for AI-driven work
- status: accepted
- date: 2026-03-24

## Context

Model-native task runners will continue to improve. That makes it strategically weak to define Harness primarily as an agent orchestration layer, a generic planner/router, or a competitor to model-native reasoning.

Harness needs a durable role that remains valuable even as Claude, Codex, and similar systems improve at decomposition and execution.

The durable value is in:

- canonical task contracts
- lifecycle correctness
- artifact-backed completion
- verification and auditability
- explicit blocked, failed, and completed semantics
- system-of-record alignment across tools such as Linear and GitHub
- treating executors as replaceable workers behind contracts

## Decision

Position Harness as a control plane and reliability layer for AI-driven work.

This means:

- Harness is not an agent runtime
- Harness is not primarily an autonomy product
- Harness does not compete on raw reasoning quality
- Harness owns correctness, traceability, verification, and enforcement
- LLMs and agents are replaceable workers behind explicit contracts
- completion is not trusted unless supported by task-appropriate artifacts and reconciliation

## Consequences

- architecture and implementation work should prioritize verification, evidence, and auditability before sophisticated planner behavior
- artifact systems such as GitHub and structured work systems such as Linear are part of the system contract, not optional metadata sinks
- executor integrations should be designed for replaceability rather than special treatment of any one model provider
- task lifecycle semantics become a first-class product boundary, not a side effect of worker behavior

## Alternatives Considered

### Harness As An Agent Orchestration Product

Rejected because model-native systems are likely to absorb more of that surface area over time.

### Harness As A Generic Multi-Agent Platform

Rejected because it over-centers worker coordination rather than correctness, evidence, and system-of-record enforcement.

### Harness As A Reliability Layer For AI-Driven Work

Selected because it gives Harness a durable control-plane role even as worker quality improves.
