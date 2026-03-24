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

Linear's movement toward an AI-native work surface strengthens this positioning rather than weakening it. Harness should not compete with Linear on work coordination or agent-facing issue management. Harness should sit underneath that surface as the layer that enforces correctness.

## Decision

Position Harness as a control plane and reliability layer for AI-driven work.

This means:

- Harness is not an agent runtime
- Harness is not primarily an autonomy product
- Harness does not compete on raw reasoning quality
- Harness does not compete with Linear on issue, project, or workflow coordination
- Harness owns correctness, traceability, verification, and enforcement
- LLMs and agents are replaceable workers behind explicit contracts
- completion is not accepted unless supported by task-appropriate artifacts and reconciliation
- Harness enforces that task completion must be backed by verifiable evidence, not executor-reported success
- Linear remains the work surface and structured-work system of record where humans and agents coordinate work

## Architectural Implications

- TaskEnvelope and related contracts must support attachment of execution artifacts and evidence
- Lifecycle transitions (especially to `completed`) must be gated by verification rules
- Integrations with systems like GitHub and Linear are required for correctness, not optional extensions
- Linear integration should optimize for system-of-record alignment and upstream write-back of verified outcomes rather than trying to replace Linear's native coordination surface
- Executor outputs must be treated as untrusted until validated against artifacts
- The system must support post-hoc audit and reconciliation of task outcomes

## Definition Of Reliability

In the context of Harness, “reliable” means:

- task state is explicitly represented and transitions are controlled
- completion is only recognized when supported by verifiable artifacts
- execution outcomes are auditable after the fact
- failures and blocked states are first-class and cannot be silently ignored
- system-of-record data (e.g. Linear, GitHub) can be reconciled against Harness state
- no task is considered complete based solely on worker-reported status

Reliability is defined by enforceable guarantees, not by worker quality.

## Consequences

- architecture and implementation work should prioritize verification, evidence, and auditability before sophisticated planner behavior
- artifact systems such as GitHub and structured work systems such as Linear are part of the system contract, not optional metadata sinks
- work-surface features such as issue intake UX, generic coordination, and project management should remain secondary to reliability and enforcement capabilities
- executor integrations should be designed for replaceability rather than special treatment of any one model provider
- task lifecycle semantics become a first-class product boundary, not a side effect of worker behavior

## Alternatives Considered

### Harness As An Agent Orchestration Product

Rejected because model-native systems are likely to absorb more of that surface area over time.

### Harness As A Generic Multi-Agent Platform

Rejected because it over-centers worker coordination rather than correctness, evidence, and system-of-record enforcement.

### Harness As A Reliability Layer For AI-Driven Work

Selected because it gives Harness a durable control-plane role even as worker quality improves.
